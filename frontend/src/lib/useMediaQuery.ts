"use client";

/**
 * Whether a CSS media query matches (design case-workspace-admin, decision 8: the case page's rail is a column from
 * 1100 px and collapsible cards below). On the server, and where `matchMedia` cannot be read, it answers false, so the
 * narrow layout (which works at every width) is the fallback.
 */
import { useEffect, useState, useSyncExternalStore, type RefObject } from "react";

export const WIDE_CASE_PAGE = "(min-width: 1100px)";

/**
 * The narrowest case workspace that holds the tabs card beside the 320 px rail: a 600 px main column, the 16 px gap
 * and the rail. With the 248 px sidebar a 1280 px window leaves a 968 px workspace, so the design's 640 px minimum
 * could not hold there; 600 px does (Deviations in the design note).
 */
export const RAIL_MIN_WORKSPACE = 600 + 16 + 320;

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener?.("change", onChange);
      return () => mql.removeEventListener?.("change", onChange);
    },
    () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false),
    () => false,
  );
}

/** The element's width in CSS pixels while it is mounted; null where it cannot be measured (no `ResizeObserver`). */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setWidth(el.getBoundingClientRect().width || null);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
