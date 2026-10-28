/**
 * The browser's session clock, pure (design session-timeout, decisions 6, 16 to 19): the phase of a session from the
 * shared last activity and the limits the last ping answered, and the ping throttle. No timer, no storage, no
 * React: `SessionWatch` reads the shared keys each second and asks these functions what to do.
 */

/** One ping a minute at most (decision 6); a constant, not a setting. */
export const PING_WINDOW_MS = 60_000;
/** Every tab looks at the shared clock once a second (decision 16). */
export const TICK_MS = 1_000;

export interface Limits {
  /** SESSION_IDLE_MINUTES in milliseconds. */
  idleMs: number;
  /** SESSION_WARNING_SECONDS in milliseconds. */
  warningMs: number;
  /** The hard limit as a `Date.now()` instant, once a ping has named it. */
  hardEnd: number | null;
  /** SESSION_MAX_HOURS, for the wording of the hard limit, once a ping has named it. */
  maxHours: number | null;
}

/** Until the first ping answers: the defaults of the API settings (30 min, 2 min) and no hard end yet. */
export const DEFAULT_LIMITS: Limits = { idleMs: 30 * 60_000, warningMs: 120_000, hardEnd: null, maxHours: null };

export type Phase =
  | { kind: "active" }
  | { kind: "warn-idle"; leftMs: number }
  | { kind: "warn-limit"; leftMs: number }
  | { kind: "expired-idle" }
  | { kind: "expired-limit" };

/** The limits of a ping answer, the hard end turned into an instant of this browser's clock. */
export function limitsFromPing(
  answer: { idle_seconds: number; warning_seconds: number; session_ends_in: number; max_hours?: number | null },
  now: number,
): Limits {
  const hours = Number(answer.max_hours);
  return {
    idleMs: answer.idle_seconds * 1000,
    warningMs: answer.warning_seconds * 1000,
    hardEnd: now + answer.session_ends_in * 1000,
    maxHours: Number.isFinite(hours) && hours > 0 ? hours : null,
  };
}

/**
 * The session's phase at `now`: the earlier of the idle end (`activity + idle`) and the hard end decides (the hard
 * limit on a tie, as on the server); within `warning` of it, the warning of that kind; at or after it, expired.
 */
export function phaseAt(now: number, activity: number, limits: Limits): Phase {
  const idleEnd = activity + limits.idleMs;
  const hardEnd = limits.hardEnd ?? Number.POSITIVE_INFINITY;
  const idleFirst = idleEnd < hardEnd;
  const end = idleFirst ? idleEnd : hardEnd;
  if (now >= end) return { kind: idleFirst ? "expired-idle" : "expired-limit" };
  if (now >= end - limits.warningMs) return { kind: idleFirst ? "warn-idle" : "warn-limit", leftMs: end - now };
  return { kind: "active" };
}

/**
 * Decision 6, as one rule over the two shared instants: ping when there is activity the server has not been told of
 * (`activity > lastPing`) and the last ping is a full window old. Called at once on activity (the leading edge) and
 * on every tick (the trailing edge, at the end of the window); quiet after that, since the ping is then newer than
 * the activity.
 */
export function shouldPing(now: number, activity: number | null, lastPing: number | null): boolean {
  if (activity === null) return false;
  if (lastPing === null) return true;
  return activity > lastPing && now - lastPing >= PING_WINDOW_MS;
}

/** `m:ss` of the time left, rounded up to the second (1:45). */
export function countdown(leftMs: number): string {
  const seconds = Math.max(0, Math.ceil(leftMs / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The whole minutes of quiet when the warning opens (28 by default). */
export function quietMinutes(limits: Limits): number {
  return Math.max(1, Math.round((limits.idleMs - limits.warningMs) / 60_000));
}
