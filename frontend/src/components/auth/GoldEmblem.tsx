"use client";

/**
 * The gold Lion Capital at the top of the sign-in frame's navy panel (design signin-gold-emblem, row 249; visual
 * reference docs/design/ui/aslms-login-emblem-mock-v2.html):
 * - the official cut-out (`BRAND.capital`) masks a gold gradient, so nothing is recoloured, drawn or traced
 *   (decision 2);
 * - it turns as a two-sided coin, so it never shows mirrored (decision 4), with "অসম চৰকাৰ" above and
 *   "सत्यमेव जयते" below in gold (decision 5);
 * - one accessible label for the emblem, every layer under it hidden (decision 6);
 * - a Pause / Play button (owner, point 1; WCAG 2.2.2) that stops all four motions and shows the still front face
 *   (decisions 7 and 8), remembered on this browser in `localStorage` (decision 9);
 * - under reduced motion the emblem is still and there is no button (decision 14).
 * With no `capital` configured, nothing is rendered.
 */
import { useState, useSyncExternalStore, type CSSProperties } from "react";

import { PauseIcon, PlayIcon } from "@/components/shell/icons";
import { usePrefersReducedMotion } from "@/components/ui/motion";
import type { BrandConfig } from "@/lib/brand";
import { BRAND } from "@/lib/brand";
import { T } from "@/lib/messages";

import s from "./auth.module.css";

/** The `localStorage` key holding `"paused"` once the person paused the emblem, or nothing. */
export const EMBLEM_MOTION_KEY = "aslms.emblemMotion";

function subscribeStorage(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readStoredPause(): boolean {
  try {
    return window.localStorage.getItem(EMBLEM_MOTION_KEY) === "paused";
  } catch {
    // localStorage unavailable (some private modes): the choice lives only in the mounted frame
    return false;
  }
}

function storePause(paused: boolean): void {
  try {
    if (paused) window.localStorage.setItem(EMBLEM_MOTION_KEY, "paused");
    else window.localStorage.removeItem(EMBLEM_MOTION_KEY);
  } catch {
    // as above: the frame's own state still holds the choice
  }
}

export function GoldEmblem({ brand = BRAND }: { brand?: BrandConfig }) {
  const capital = brand.capital;
  const reduced = usePrefersReducedMotion();
  // the server always renders the turning state; a stored pause takes effect at hydration
  const stored = useSyncExternalStore(subscribeStorage, readStoredPause, () => false);
  const [choice, setChoice] = useState<boolean | null>(null);
  if (!capital) return null;
  const paused = choice ?? stored;
  const E = T.auth.frame.emblem;

  function toggle() {
    const next = !paused;
    setChoice(next);
    storePause(next);
  }

  const face = (
    <div className={s.glow}>
      <div className={s.gold} />
    </div>
  );

  return (
    <div className={s.emblemBlock} data-motion={paused ? "paused" : undefined}>
      <div className={s.emblemArt} role="img" aria-label={T.brand.emblemAlt}>
        <span className={`${s.goldText} ${s.assamese}`} lang="as" aria-hidden="true">
          {E.assamese}
        </span>
        <div className={s.stage} style={{ "--emblem-mask": `url("${capital.src}")` } as CSSProperties} aria-hidden="true">
          <div className={s.spinner}>
            <div className={s.face}>{face}</div>
            <div className={`${s.face} ${s.back}`}>{face}</div>
          </div>
          <div className={s.shadow} />
        </div>
        <span className={`${s.goldText} ${s.motto}`} lang="sa" aria-hidden="true">
          {E.motto}
        </span>
      </div>
      {reduced ? null : (
        <button type="button" className={s.motionBtn} aria-label={paused ? E.playLabel : E.pauseLabel} onClick={toggle}>
          {paused ? <PlayIcon /> : <PauseIcon />}
          <span>{paused ? E.play : E.pause}</span>
        </button>
      )}
    </div>
  );
}
