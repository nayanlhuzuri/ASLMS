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

/** Where a count stands: from `from` to `to` (null before any number), `frame` of the frames done. */
interface Count {
  from: number;
  to: number | null;
  frame: number;
}

function countValue(c: Count, frames: number): number {
  if (c.to === null) return 0;
  return c.frame >= frames ? c.to : Math.round(c.from + ((c.to - c.from) * c.frame) / frames);
}

/**
 * A number counting to `target` over about `frames` animation frames (the dashboard headline, the Data Collection
 * figures). On first mount it counts up from 0 (the entry motion); when the target changes it counts from the value
 * shown at that moment, up or down, never through 0, and a change in the middle of a count starts from the value then
 * shown (design data-collection-redesign-advisories, decision 5). Under reduced motion, or without a number or with 0,
 * the final value is returned at once.
 */
export function useCountUp(target: number | null | undefined, frames = 12): number | null | undefined {
  const reduced = usePrefersReducedMotion();
  const [count, setCount] = useState<Count>({ from: 0, to: null, frame: 0 });
  // a NaN or infinite target is treated as no number: shown as given, never counted (NaN !== NaN would re-render forever)
  const finite = typeof target === "number" && Number.isFinite(target);
  const animate = !reduced && finite && target !== 0 && typeof requestAnimationFrame === "function";
  if (animate && count.to !== target) {
    // derived from the change of `target` during render (React's documented pattern, as `usePresence`), so the first
    // render after a new target shows the value already on screen, never 0
    setCount({ from: countValue(count, frames), to: target, frame: 0 });
  } else if (!animate && finite && (count.to !== target || count.frame < frames)) {
    setCount({ from: target, to: target, frame: frames });
  } else if (!finite && count.to !== null) {
    setCount({ from: 0, to: null, frame: 0 });
  }
  useEffect(() => {
    if (!animate || !finite) return;
    let frame = 0;
    let id = 0;
    const step = () => {
      frame += 1;
      setCount((prev) => (prev.to === target ? { ...prev, frame } : prev));
      if (frame < frames) id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [animate, finite, target, frames]);
  if (!animate || !finite) return target;
  return countValue(count, frames);
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
