"use client";

/**
 * Motion with reduced motion respected (design portal-ui-redesign, decision 13). The CSS reads the duration tokens,
 * which become 0 ms under `prefers-reduced-motion: reduce`; the JavaScript parts read the same media query here.
 * No animation library. Where the media query cannot be read (a browser without `matchMedia`), nothing animates.
 */
import { useEffect, useLayoutEffect, useState, useSyncExternalStore, type DependencyList, type RefObject } from "react";

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

// a layout effect in the browser (the mark is placed before paint), a plain effect on the server
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** The box of a sliding mark, in the container's coordinates. */
export interface MarkBox {
  left: number;
  width: number;
}

/**
 * The place of a sliding mark (design portal-motion, decision 10): the Tabs underline and the SegmentedSwitch thumb.
 * Measures the container's item matching `selector` (`offsetLeft`, `offsetWidth`) in a layout effect, again whenever
 * the container or one of its items changes size (a `ResizeObserver` on the container and on each child that is not
 * `aria-hidden`, so the mark itself is never watched) and once more when the fonts are ready. Returns null while
 * nothing matches or before the first measurement, so the mark mounts in place and never slides in from 0.
 */
export function useSlidingMark(containerRef: RefObject<HTMLElement | null>, selector: string, deps: DependencyList): MarkBox | null {
  const [box, setBox] = useState<MarkBox | null>(null);
  useIsoLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const place = () => {
      const item = el.querySelector<HTMLElement>(selector);
      const next = item ? { left: item.offsetLeft, width: item.offsetWidth } : null;
      setBox((prev) => (prev && next && prev.left === next.left && prev.width === next.width ? prev : next));
    };
    place();
    let live = true;
    const fonts = typeof document !== "undefined" ? (document as Document & { fonts?: FontFaceSet }).fonts : undefined;
    fonts?.ready?.then(() => {
      if (live) place();
    });
    if (typeof ResizeObserver === "undefined") {
      return () => {
        live = false;
      };
    }
    const observer = new ResizeObserver(place);
    observer.observe(el);
    Array.from(el.children).forEach((child) => {
      if (child.getAttribute("aria-hidden") !== "true") observer.observe(child);
    });
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [selector, ...deps]);
  return box;
}
