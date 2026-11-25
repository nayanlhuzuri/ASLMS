/**
 * The home page's Sign In links move to the form (design home-page, decision 11). Each link is a real
 * `<a href="#sign-in">`, so without JavaScript the browser jumps to the card. With JavaScript one click listener on the
 * page (`listenForSignInLinks`, installed by the card) takes the click instead: no hash is added to the address, the
 * window scrolls to the card over `DURATION.med` with an ease-out (or at once under reduced motion), and the step's
 * first field gets the focus with `preventScroll`, so the scroll is never doubled. When the card is already wholly in
 * view, only the focus moves. CSS `scroll-behavior: smooth` is not used: its length cannot be set.
 */
import { DURATION } from "@/components/ui/motion";

/** The card's id, the Sign In links' target. */
export const SIGN_IN_ID = "sign-in";

const LINK_SELECTOR = `a[href="#${SIGN_IN_ID}"]`;

/** The first field of the step on show: the e-mail on the password step, the code on the code step. */
export function activeField(card: HTMLElement): HTMLInputElement | null {
  return card.querySelector<HTMLInputElement>("[data-step]:not([inert]) input:not([type=hidden])");
}

/** The gap left above the card, `--s4` (16 px when the token cannot be read). */
function topGap(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--s4");
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : 16;
}

function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

/** The computer's reduced-motion setting at this moment (true when it cannot be read, as `usePrefersReducedMotion`). */
export function reducedNow(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function now(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

/**
 * Moves to the sign-in card and focuses its field. `reduced` is the computer's reduced-motion setting. Returns the
 * frame request id of a running scroll, or null when no scroll was needed or it happened at once.
 */
export function jumpToSignIn(reduced: boolean = reducedNow()): number | null {
  const card = document.getElementById(SIGN_IN_ID);
  if (!card) return null;
  const focus = () => activeField(card)?.focus({ preventScroll: true });
  const box = card.getBoundingClientRect();
  const viewport = window.innerHeight || document.documentElement.clientHeight;
  if (box.top >= 0 && box.bottom <= viewport) {
    focus();
    return null;
  }
  if (reduced || typeof requestAnimationFrame !== "function") {
    // the card's scroll-margin-top keeps the same gap as the animated scroll
    card.scrollIntoView({ block: "start" });
    focus();
    return null;
  }
  const from = window.scrollY;
  const most = Math.max(0, document.documentElement.scrollHeight - viewport);
  const to = Math.min(most, Math.max(0, from + box.top - topGap()));
  const start = now();
  let id = 0;
  const step = () => {
    const t = Math.min(1, (now() - start) / DURATION.med);
    window.scrollTo(0, from + (to - from) * easeOut(t));
    if (t < 1) id = requestAnimationFrame(step);
    else focus();
  };
  id = requestAnimationFrame(step);
  return id;
}

/**
 * The one click listener of the page: a click on any Sign In link (`a[href="#sign-in"]`) moves to the card instead of
 * following the hash. The reduced-motion setting is read at click time. Returns the function that removes the listener.
 */
export function listenForSignInLinks(): () => void {
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const target = e.target instanceof Element ? e.target.closest(LINK_SELECTOR) : null;
    if (!target) return;
    e.preventDefault();
    jumpToSignIn(reducedNow());
  };
  document.addEventListener("click", onClick);
  return () => document.removeEventListener("click", onClick);
}
