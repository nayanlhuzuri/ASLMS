import { describe, expect, it } from "vitest";

import {
  countdown,
  DEFAULT_LIMITS,
  limitsFromPing,
  phaseAt,
  PING_WINDOW_MS,
  quietMinutes,
  shouldPing,
  type Limits,
} from "./clock";

const MIN = 60_000;
const T0 = 1_800_000_000_000;

describe("phaseAt (design session-timeout, decisions 17 to 19)", () => {
  const limits: Limits = { idleMs: 30 * MIN, warningMs: 2 * MIN, hardEnd: T0 + 12 * 60 * MIN, maxHours: 12 };

  it.each([
    ["active at 27:59", 27 * MIN + 59_000, "active"],
    ["warn-idle at 28:00", 28 * MIN, "warn-idle"],
    ["warn-idle at 29:59", 29 * MIN + 59_000, "warn-idle"],
    ["expired-idle at 30:00", 30 * MIN, "expired-idle"],
  ])("%s", (_name, after, kind) => {
    expect(phaseAt(T0 + after, T0, limits).kind).toBe(kind);
  });

  it("counts the time left in the warning", () => {
    expect(phaseAt(T0 + 28 * MIN + 15_000, T0, limits)).toEqual({ kind: "warn-idle", leftMs: 105_000 });
  });

  it("warns of the hard limit and expires at it when it comes first", () => {
    const activity = T0 + 12 * 60 * MIN - 10 * MIN; // active ten minutes before the limit
    expect(phaseAt(activity + 7 * MIN, activity, limits).kind).toBe("active");
    expect(phaseAt(activity + 8 * MIN, activity, limits)).toEqual({ kind: "warn-limit", leftMs: 2 * MIN });
    expect(phaseAt(activity + 10 * MIN, activity, limits).kind).toBe("expired-limit");
  });

  it("lets the earlier deadline decide when both fall inside the window", () => {
    const hardSoon: Limits = { ...limits, hardEnd: T0 + 30 * MIN + 30_000 };
    expect(phaseAt(T0 + 29 * MIN, T0, hardSoon).kind).toBe("warn-idle");
    const hardFirst: Limits = { ...limits, hardEnd: T0 + 29 * MIN + 30_000 };
    expect(phaseAt(T0 + 29 * MIN, T0, hardFirst).kind).toBe("warn-limit");
    expect(phaseAt(T0 + 29 * MIN + 30_000, T0, hardFirst).kind).toBe("expired-limit");
  });

  it("has no hard end before the first ping", () => {
    expect(phaseAt(T0 + 20 * 60 * MIN, T0 + 20 * 60 * MIN - MIN, DEFAULT_LIMITS).kind).toBe("active");
  });
});

describe("shouldPing (decision 6)", () => {
  it("sends a leading ping, then one trailing ping, then nothing while quiet", () => {
    // first activity, never pinged: at once
    expect(shouldPing(T0, T0, null)).toBe(true);
    let lastPing = T0;
    // more activity inside the window: not yet
    const activity = T0 + 20_000;
    expect(shouldPing(T0 + 20_000, activity, lastPing)).toBe(false);
    expect(shouldPing(T0 + PING_WINDOW_MS - 1, activity, lastPing)).toBe(false);
    // the end of the window: the trailing ping
    expect(shouldPing(T0 + PING_WINDOW_MS, activity, lastPing)).toBe(true);
    lastPing = T0 + PING_WINDOW_MS;
    // quiet afterwards: the ping is newer than the activity
    expect(shouldPing(T0 + 10 * PING_WINDOW_MS, activity, lastPing)).toBe(false);
  });

  it("pings at once on activity when the last ping is a minute old", () => {
    expect(shouldPing(T0 + PING_WINDOW_MS, T0 + PING_WINDOW_MS, T0)).toBe(true);
  });

  it("needs activity", () => {
    expect(shouldPing(T0, null, null)).toBe(false);
  });
});

describe("helpers", () => {
  it("formats the countdown as m:ss, rounded up", () => {
    expect(countdown(105_000)).toBe("1:45");
    expect(countdown(104_200)).toBe("1:45");
    expect(countdown(120_000)).toBe("2:00");
    expect(countdown(0)).toBe("0:00");
    expect(countdown(-5)).toBe("0:00");
  });

  it("reads the ping answer and the quiet minutes", () => {
    const l = limitsFromPing({ idle_seconds: 1800, warning_seconds: 120, session_ends_in: 43_200, max_hours: 8 }, T0);
    expect(l).toEqual({ idleMs: 30 * MIN, warningMs: 2 * MIN, hardEnd: T0 + 43_200_000, maxHours: 8 });
    expect(quietMinutes(l)).toBe(28);
    expect(quietMinutes({ idleMs: 3 * MIN, warningMs: MIN, hardEnd: null, maxHours: null })).toBe(2);
    // an older API without max_hours
    expect(limitsFromPing({ idle_seconds: 1800, warning_seconds: 120, session_ends_in: 60 }, T0).maxHours).toBeNull();
  });
});
