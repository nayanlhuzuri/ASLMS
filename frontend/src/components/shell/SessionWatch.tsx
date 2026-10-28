"use client";

/**
 * The session watch (design session-timeout, decisions 5, 6 and 16 to 20), mounted last in `PortalShell` and in the
 * welcome layout, never on the public pages.
 * - **Activity** is the person's own: `pointerdown`, `keydown`, `wheel` and `touchstart` on the window (capture,
 *   passive), a client-side route change and the page load. Requests, focus, visibility and `mousemove` are not.
 *   Activity is written to the shared clock and pinged to `POST /me/activity` at most once a minute, with one
 *   trailing ping; Stay Signed In pings at once.
 * - **Each second** every tab reads the shared clock (and at once on another tab's write): within the warning of the
 *   idle end it shows "Are You Still There?", within it of the hard limit "Session Ending Soon" (the earlier deadline
 *   decides), and at the deadline the first tab to see it writes `out`, has the web server clear the cookies (the
 *   API is not told: its own check and sweep record the idle or limit end), clears the cache and goes to
 *   `/login?reason=…&next=…`; the other tabs follow without calling the API. A 1-second tick, never a long timer,
 *   so a laptop woken after an hour signs out on its first tick.
 * - While a dialog is open the page's listeners are paused, so a stray scroll behind it does not dismiss it.
 * Nothing the person typed is saved for them (decision 20).
 */
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, Dialog } from "@/components/ui";
import { api, session, signedOut } from "@/lib/api/client";
import { T } from "@/lib/messages";
import {
  countdown,
  limitsFromPing,
  phaseAt,
  quietMinutes,
  shouldPing,
  TICK_MS,
  type Limits,
  type Phase,
} from "@/lib/session/clock";
import { sessionStore, type OutReason, type SessionStore } from "@/lib/session/store";

interface ActivityAnswer {
  idle_seconds: number;
  warning_seconds: number;
  idle_ends_in: number;
  session_ends_in: number;
  max_hours: number;
}

const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

type Shown = { kind: "none" } | { kind: "warn-idle"; leftMs: number } | { kind: "warn-limit"; leftMs: number };

/** Writes the person's Sign Out to the shared clock so every tab leaves (decision 19). */
export function broadcastSignOut(store: SessionStore = sessionStore()): void {
  store.setOut("signed_out");
}

export function SessionWatch() {
  const pathname = usePathname();
  const store = sessionStore();
  const [shown, setShown] = useState<Shown>({ kind: "none" });
  const [limits, setLimits] = useState<Limits>(() => store.limits());
  const mountedAt = useRef(0);
  const leaving = useRef(false);
  const dialogOpen = useRef(false);
  const dismissedEnd = useRef<number | null>(null);
  const firstPath = useRef(true);

  const ping = useCallback(() => {
    const now = Date.now();
    store.setPing(now);
    api<ActivityAnswer>("/me/activity", { method: "POST" })
      .then((answer) => {
        if (!answer) return;
        store.setLimits(limitsFromPing(answer, Date.now()));
      })
      .catch(() => undefined); // a lapsed session is handled by the client (out + sign-in page); a network error waits
  }, [store]);

  const act = useCallback(
    (force = false) => {
      if (leaving.current) return;
      const now = Date.now();
      store.setActivity(now);
      if (force || shouldPing(now, now, store.ping())) ping();
    },
    [store, ping],
  );

  const leave = useCallback(
    (reason: OutReason, { own }: { own: boolean }) => {
      if (leaving.current) return;
      leaving.current = true;
      dialogOpen.current = false;
      setShown({ kind: "none" });
      if (!own) {
        signedOut(reason, { broadcast: false });
        return;
      }
      store.setOut(reason);
      // only the cookies go: the API's check and sweep record the idle or limit end (deviation 12), never a logout
      void session("logout", { reason })
        .catch(() => undefined)
        .finally(() => signedOut(reason, { broadcast: false }));
    },
    [store],
  );

  const evaluate = useCallback(() => {
    if (leaving.current) return;
    const now = Date.now();
    const out = store.out();
    if (out && out.at > mountedAt.current) {
      leave(out.reason, { own: false });
      return;
    }
    const current = store.limits();
    setLimits((was) =>
      was.idleMs === current.idleMs &&
      was.warningMs === current.warningMs &&
      was.hardEnd === current.hardEnd &&
      was.maxHours === current.maxHours
        ? was
        : current,
    );
    const phase: Phase = phaseAt(now, store.activity() ?? mountedAt.current, current);
    if (phase.kind === "expired-idle" || phase.kind === "expired-limit") {
      leave(phase.kind === "expired-idle" ? "idle" : "limit", { own: true });
      return;
    }
    let next: Shown = { kind: "none" };
    if (phase.kind === "warn-idle") next = { kind: "warn-idle", leftMs: phase.leftMs };
    else if (phase.kind === "warn-limit" && dismissedEnd.current !== current.hardEnd) {
      next = { kind: "warn-limit", leftMs: phase.leftMs };
    }
    dialogOpen.current = next.kind !== "none";
    setShown((was) => (was.kind === "none" && next.kind === "none" ? was : next));
    // the trailing ping: activity the server has not been told of, once the window has passed
    if (shouldPing(now, store.activity(), store.ping())) ping();
  }, [store, leave, ping]);

  // the page load is activity (decision 5); a hard end already past belongs to an earlier session
  useEffect(() => {
    mountedAt.current = Date.now();
    store.dropPastHardEnd(mountedAt.current);
    act(true);
    evaluate();
    const timer = window.setInterval(evaluate, TICK_MS);
    const unsubscribe = store.subscribe(() => evaluate());
    const onActivity = () => {
      if (!dialogOpen.current) act();
    };
    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, onActivity, { capture: true, passive: true });
    return () => {
      window.clearInterval(timer);
      unsubscribe();
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, onActivity, { capture: true });
    };
  }, [store, act, evaluate]);

  // a client-side route change is activity (the first path is the page load, counted above)
  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false;
      return;
    }
    act();
  }, [pathname, act]);

  const stay = useCallback(() => {
    dialogOpen.current = false;
    act(true);
    evaluate();
  }, [act, evaluate]);

  /** Sign Out (the warning) and Sign in Now (the notice): every tab leaves; this one to `/login?next=<here>`. */
  const signOutNow = useCallback(() => {
    if (leaving.current) return;
    leaving.current = true;
    dialogOpen.current = false;
    setShown({ kind: "none" });
    broadcastSignOut(store);
    void session("logout")
      .catch(() => undefined)
      .finally(() => signedOut(null, { broadcast: false }));
  }, [store]);

  const keepWorking = useCallback(() => {
    dismissedEnd.current = store.limits().hardEnd;
    dialogOpen.current = false;
    setShown({ kind: "none" });
  }, [store]);

  if (shown.kind === "warn-idle") {
    return (
      <Dialog
        open
        title={T.session.warnTitle}
        onClose={stay}
        footer={
          <>
            <Button variant="secondary" onClick={signOutNow}>
              {T.session.signOutButton}
            </Button>
            <Button data-autofocus="" onClick={stay}>
              {T.session.stayButton}
            </Button>
          </>
        }
      >
        <p>{T.session.warnBody(countdown(shown.leftMs), quietMinutes(limits))}</p>
        <p className="visually-hidden" role="status" aria-live="polite">
          {T.session.warnAnnounceMessage}
        </p>
      </Dialog>
    );
  }
  if (shown.kind === "warn-limit") {
    return (
      <Dialog
        open
        title={T.session.limitTitle}
        onClose={keepWorking}
        footer={
          <>
            <Button variant="secondary" onClick={signOutNow}>
              {T.session.signInNowButton}
            </Button>
            <Button data-autofocus="" onClick={keepWorking}>
              {T.session.continueButton}
            </Button>
          </>
        }
      >
        <p>{T.session.limitBody(countdown(shown.leftMs), limits.maxHours)}</p>
        <p className="visually-hidden" role="status" aria-live="polite">
          {T.session.limitAnnounceMessage}
        </p>
      </Dialog>
    );
  }
  return null;
}
