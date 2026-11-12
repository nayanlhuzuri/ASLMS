/**
 * "An overlay has opened" (design control-spacing-sweep, decision 17): every overlay that runs `useOverlay` (the kit
 * `Dialog`, `ConfirmDialog`, `Modal`, `SidePanel` and the phone drawer) calls `notifyOverlayOpen()` once each time it
 * becomes active, after the focus has moved in; the confirmation toast listens and closes, so it never sits over the
 * overlay out of reach of its focus trap. A module of its own so that `feedback.tsx` does not import `overlays.tsx`
 * (which imports `ErrorBanner` from `feedback.tsx`).
 */

type Listener = () => void;

const listeners = new Set<Listener>();

/** Runs `listener` on every overlay opening; returns the unsubscribe. */
export function onOverlayOpen(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Tells every listener that an overlay has just opened. */
export function notifyOverlayOpen(): void {
  for (const listener of Array.from(listeners)) listener();
}
