/**
 * The session clock every tab of one browser shares (design session-timeout, decision 16), in `localStorage`:
 * - `aslms.session.activity`: the last activity, in milliseconds;
 * - `aslms.session.ping`: the last ping;
 * - `aslms.session.limits`: `idle_seconds`, `warning_seconds` and the hard end from the last ping answer;
 * - `aslms.session.out`: `{reason, at}`, written when any tab signs out.
 * A `storage` listener tells a tab at once of another tab's write. When `localStorage` is not available (some private
 * modes), the same state is kept in memory and works for one tab. Nothing typed by the person is ever stored here.
 */
import { DEFAULT_LIMITS, type Limits } from "./clock";

export const KEYS = {
  activity: "aslms.session.activity",
  ping: "aslms.session.ping",
  limits: "aslms.session.limits",
  out: "aslms.session.out",
} as const;

/** Why every tab leaves: the idle end, the hard limit, a person's Sign Out, or a plain refusal (no reason shown). */
export type OutReason = "idle" | "limit" | "signed_out" | null;

export interface Out {
  reason: OutReason;
  at: number;
}

export interface StoredLimits {
  idle_seconds: number;
  warning_seconds: number;
  /** `Date.now()` instant of the hard limit, or null before the first ping. */
  hard_end: number | null;
  /** SESSION_MAX_HOURS from the ping answer, or null. */
  max_hours?: number | null;
}

export interface SessionStore {
  readonly persistent: boolean;
  activity(): number | null;
  setActivity(at: number): void;
  ping(): number | null;
  setPing(at: number): void;
  limits(): Limits;
  /** The stored limits as the ping answered them (the sign-in page's figures), or null. */
  storedLimits(): StoredLimits | null;
  setLimits(limits: Limits): void;
  /** Forgets the stored limits (a successful code step starts a new session, review finding 2). */
  clearLimits(): void;
  /** Forgets a hard end already past (a sign-in after the last session's limit); the next ping names the new one. */
  dropPastHardEnd(now: number): void;
  out(): Out | null;
  setOut(reason: OutReason, at?: number): void;
  /** Calls `listener` when another tab writes one of the keys; the unsubscribe function. */
  subscribe(listener: (key: string) => void): () => void;
}

interface Backend {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

function memoryBackend(): Backend {
  const map = new Map<string, string>();
  return { get: (k) => map.get(k) ?? null, set: (k, v) => void map.set(k, v), remove: (k) => void map.delete(k) };
}

/** `localStorage` when it can be written, else null. */
function localBackend(): Backend | null {
  try {
    if (typeof window === "undefined") return null;
    const ls = window.localStorage;
    const probe = "aslms.session.probe";
    ls.setItem(probe, "1");
    ls.removeItem(probe);
    return {
      get: (k) => {
        try {
          return ls.getItem(k);
        } catch {
          return null;
        }
      },
      set: (k, v) => {
        try {
          ls.setItem(k, v);
        } catch {
          // a full or revoked storage: the tab still works on what it holds
        }
      },
      remove: (k) => {
        try {
          ls.removeItem(k);
        } catch {
          // nothing to forget
        }
      },
    };
  } catch {
    return null;
  }
}

function num(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function parse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function validLimits(v: StoredLimits | null): StoredLimits | null {
  if (!v || typeof v !== "object") return null;
  const idle = Number(v.idle_seconds);
  const warning = Number(v.warning_seconds);
  if (!Number.isFinite(idle) || idle <= 0 || !Number.isFinite(warning) || warning <= 0) return null;
  const hard = v.hard_end === null || v.hard_end === undefined ? null : Number(v.hard_end);
  const hours = v.max_hours === null || v.max_hours === undefined ? null : Number(v.max_hours);
  return {
    idle_seconds: idle,
    warning_seconds: warning,
    hard_end: hard !== null && Number.isFinite(hard) ? hard : null,
    max_hours: hours !== null && Number.isFinite(hours) && hours > 0 ? hours : null,
  };
}

export function createStore(backend: Backend | null = localBackend()): SessionStore {
  const persistent = backend !== null;
  const b = backend ?? memoryBackend();
  const OUT_REASONS = new Set(["idle", "limit", "signed_out"]);
  const store: SessionStore = {
    persistent,
    activity: () => num(b.get(KEYS.activity)),
    setActivity: (at) => b.set(KEYS.activity, String(at)),
    ping: () => num(b.get(KEYS.ping)),
    setPing: (at) => b.set(KEYS.ping, String(at)),
    storedLimits: () => validLimits(parse<StoredLimits>(b.get(KEYS.limits))),
    limits: () => {
      const v = store.storedLimits();
      if (!v) return DEFAULT_LIMITS;
      return {
        idleMs: v.idle_seconds * 1000,
        warningMs: v.warning_seconds * 1000,
        hardEnd: v.hard_end,
        maxHours: v.max_hours ?? null,
      };
    },
    setLimits: (l) =>
      b.set(
        KEYS.limits,
        JSON.stringify({
          idle_seconds: l.idleMs / 1000,
          warning_seconds: l.warningMs / 1000,
          hard_end: l.hardEnd,
          max_hours: l.maxHours,
        }),
      ),
    clearLimits: () => b.remove(KEYS.limits),
    dropPastHardEnd: (now) => {
      const v = store.storedLimits();
      if (v && v.hard_end !== null && v.hard_end <= now) b.set(KEYS.limits, JSON.stringify({ ...v, hard_end: null }));
    },
    out: () => {
      const v = parse<Out>(b.get(KEYS.out));
      if (!v || typeof v !== "object" || !Number.isFinite(Number(v.at))) return null;
      const reason = typeof v.reason === "string" && OUT_REASONS.has(v.reason) ? v.reason : null;
      return { reason, at: Number(v.at) };
    },
    setOut: (reason, at = Date.now()) => b.set(KEYS.out, JSON.stringify({ reason, at })),
    subscribe: (listener) => {
      if (!persistent || typeof window === "undefined") return () => undefined;
      const onStorage = (e: StorageEvent) => {
        if (e.key && (Object.values(KEYS) as string[]).includes(e.key)) listener(e.key);
      };
      window.addEventListener("storage", onStorage);
      return () => window.removeEventListener("storage", onStorage);
    },
  };
  return store;
}

let shared: SessionStore | null = null;

/** The page's one store (the API client and the watcher write the same keys). */
export function sessionStore(): SessionStore {
  if (!shared) shared = createStore();
  return shared;
}

/** Tests only: the next `sessionStore()` is built afresh (after `localStorage` was replaced or cleared). */
export function resetSessionStore(): void {
  shared = null;
}

/**
 * The sign-in page's banner for `?reason=` (design session-timeout, decision 20): idle, limit or signed_out, the idle
 * minutes and the limit's hours taken from the shared clock (never from the address, so a crafted link cannot show false figures); null for
 * any other reason.
 */
export function signOutReasonText(
  reason: string | null,
  stored: StoredLimits | null,
  texts: {
    idleMessage: (minutes: number | null) => string;
    limitMessage: (hours: number | null) => string;
    signedOutMessage: string;
  },
): string | null {
  if (reason === "idle") {
    const minutes = stored ? Math.round(stored.idle_seconds / 60) : null;
    return texts.idleMessage(minutes && minutes > 0 ? minutes : null);
  }
  if (reason === "limit") return texts.limitMessage(stored?.max_hours ?? null);
  if (reason === "signed_out") return texts.signedOutMessage;
  return null;
}
