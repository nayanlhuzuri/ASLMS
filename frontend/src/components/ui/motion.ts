"use client";

/**
 * Motion with reduced motion respected (design portal-ui-redesign, decision 13). The CSS reads the duration tokens,
 * which become 0 ms under `prefers-reduced-motion: reduce`; the JavaScript parts read the same media query here.
 * No animation library. Where the media query cannot be read (a browser without `matchMedia`), nothing animates.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

/** The durations of the motion tokens, in milliseconds (`--fast`, `--med`, `--slow`). */
export const DURATION = { fast: 150, med: 220, slow: 320 } as const;

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const mql = window.matchMedia(QUERY);
  mql.addEventListener?.("change", onChange);
  return () => mql.removeEventListener?.("change", onChange);
}

function snapshot(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia(QUERY).matches;
}

/** True when the computer asks for reduced motion (or the query cannot be read). */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}

/**
 * Keeps a closing element mounted for its exit animation: `mounted` stays true for `ms` after `open` turns false,
 * with `closing` true meanwhile. Under reduced motion the element unmounts at once.
 */
export function usePresence(open: boolean, ms: number): { mounted: boolean; closing: boolean } {
  const reduced = usePrefersReducedMotion();
  const duration = reduced ? 0 : ms;
  const [closing, setClosing] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    // derived from the change of `open` during render (React's documented pattern), so no frame shows it unmounted
    setWasOpen(open);
    setClosing(!open && duration > 0);
  }
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => setClosing(false), duration);
    return () => clearTimeout(timer);
  }, [closing, duration]);
  return { mounted: open || closing, closing: closing && !open };
}

/**
 * A number counting up to `target` over about `frames` animation frames (the dashboard headline). Under reduced
 * motion, or without a number, the final value is returned at once.
 */
export function useCountUp(target: number | null | undefined, frames = 12): number | null | undefined {
  const reduced = usePrefersReducedMotion();
  const [anim, setAnim] = useState<{ target: number | null; frame: number }>({ target: null, frame: 0 });
  const animate = !reduced && typeof target === "number" && target !== 0 && typeof requestAnimationFrame === "function";
  useEffect(() => {
    if (!animate || typeof target !== "number") return;
    let frame = 0;
    let id = 0;
    const step = () => {
      frame += 1;
      setAnim({ target, frame });
      if (frame < frames) id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [animate, target, frames]);
  if (!animate || typeof target !== "number") return target;
  const frame = anim.target === target ? anim.frame : 0;
  return frame >= frames ? target : Math.round((target * frame) / frames);
}
