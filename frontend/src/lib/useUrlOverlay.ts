"use client";

/**
 * An overlay whose address carries one query parameter (`?case=` on Case claim, `?api=` on System health), with
 * consistent history (design portal-ui-polish, decision 10):
 * - `open(value)` pushes the address with the parameter, and once the page shows it, marks that history entry in
 *   `history.state` as pushed by this page;
 * - `close()` goes back when the current entry is the one this page pushed, so Back afterwards leaves the page
 *   instead of showing the same list again;
 * - otherwise (an address opened directly, a bookmark, a mail link) `close()` replaces the address without the
 *   parameter.
 * The mark is merged into the router's own entry state; if a later navigation drops it, `close()` replaces, which is
 * the older behaviour and never loses the page.
 */
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { queryString, type Params } from "./params";

/** The `history.state` key of the mark. */
export const OVERLAY_MARK = "__aslmsOverlay";

function markOf(param: string, value: string): string {
  return `${param}=${value}`;
}

function currentMark(): unknown {
  if (typeof window === "undefined") return undefined;
  const state = window.history.state as Record<string, unknown> | null;
  return state ? state[OVERLAY_MARK] : undefined;
}

export function useUrlOverlay(param: string, params: Params, path: string) {
  const router = useRouter();
  const value = params[param] || null;
  // the value this page pushed and has not yet marked
  const pending = useRef<string | null>(null);

  useEffect(() => {
    if (!value || pending.current !== value) return;
    pending.current = null;
    const state = (window.history.state as Record<string, unknown> | null) ?? {};
    window.history.replaceState({ ...state, [OVERLAY_MARK]: markOf(param, value) }, "", window.location.href);
  }, [param, value]);

  function open(next: string) {
    pending.current = next;
    router.push(path + queryString({ ...params, [param]: next }));
  }

  function close() {
    pending.current = null;
    if (value && currentMark() === markOf(param, value)) {
      router.back();
      return;
    }
    const rest: Params = { ...params };
    delete rest[param];
    router.replace(path + queryString(rest));
  }

  return { value, open, close };
}
