import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, resetClientHooks, setClientHooks } from "@/lib/api/client";
import { createStore, KEYS, resetSessionStore, sessionStore } from "@/lib/session/store";
import { browserApi } from "@/test/render";
import { nav, resetNav } from "@/test/nav";

import { SessionWatch } from "./SessionWatch";

const MIN = 60_000;
const T0 = new Date("2026-10-27T05:00:00Z").getTime();
const DEFAULT_PING = {
  idle_seconds: 1800,
  warning_seconds: 120,
  idle_ends_in: 1800,
  session_ends_in: 43_200,
  max_hours: 12,
};

const navigate = vi.fn();
const clearCache = vi.fn();

function scripted(ping: Record<string, number> = DEFAULT_PING) {
  return browserApi({
    "POST /me/activity": ping,
    "POST session:/logout": () => new Response(null, { status: 204 }),
    "GET /alerts/counts": { unread: 0 },
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await flush();
}

function logoutBodies(calls: { path: string; body: unknown }[]) {
  return calls.filter((c) => c.path === "session:/logout").map((c) => c.body);
}

function pings(calls: { method: string; path: string }[]) {
  return calls.filter((c) => c.method === "POST" && c.path === "/me/activity").length;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(T0);
  localStorage.clear();
  resetSessionStore();
  resetNav("/cases/x");
  navigate.mockReset();
  clearCache.mockReset();
  setClientHooks({ navigate, clearCache, currentPath: () => "/cases/x" });
});

afterEach(() => {
  resetClientHooks();
  vi.useRealTimers();
});

describe("SessionWatch (design session-timeout)", () => {
  it("pings on the page load and opens the warning at 28:00 with the countdown, Stay Signed In focused", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    expect(pings(browser.calls)).toBe(1);
    await advance(28 * MIN - 1000);
    expect(screen.queryByRole("dialog")).toBeNull();
    await advance(1000);
    expect(screen.getByRole("dialog", { name: "Are You Still There?" })).toBeInTheDocument();
    expect(screen.getByText(/signed out in 2:00 because there has been no activity for 28 minutes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay Signed In" })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("Choose Stay Signed In to continue.");
    await advance(15_000);
    expect(screen.getByText(/signed out in 1:45/)).toBeInTheDocument();
  });

  it("Stay Signed In pings at once and closes the warning", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    await advance(28 * MIN + 5000);
    const before = pings(browser.calls);
    fireEvent.click(screen.getByRole("button", { name: "Stay Signed In" }));
    await flush();
    expect(pings(browser.calls)).toBe(before + 1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(Number(localStorage.getItem(KEYS.activity))).toBe(Date.now());
  });

  it("Escape counts as Stay Signed In", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    await advance(28 * MIN);
    const before = pings(browser.calls);
    fireEvent.keyDown(document, { key: "Escape" });
    await flush();
    expect(pings(browser.calls)).toBe(before + 1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("at 30:00 writes out, calls the sign-out, clears the cache and goes to /login?reason=idle&next=", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    await advance(30 * MIN);
    await flush();
    expect(logoutBodies(browser.calls)).toEqual([{ reason: "idle" }]); // the cookies only: the API records the end
    expect(clearCache).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/login?reason=idle&next=%2Fcases%2Fx");
    expect(JSON.parse(localStorage.getItem(KEYS.out)!)).toMatchObject({ reason: "idle" });
  });

  it("api() calls and query refetches do not move the clock", async () => {
    scripted();
    render(<SessionWatch />);
    await flush();
    const activity = localStorage.getItem(KEYS.activity);
    await advance(5 * MIN);
    for (let i = 0; i < 3; i += 1) await act(async () => void (await api("/alerts/counts")));
    expect(localStorage.getItem(KEYS.activity)).toBe(activity);
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    fireEvent.mouseMove(window);
    expect(localStorage.getItem(KEYS.activity)).toBe(activity);
  });

  it("counts clicks, keys, wheel, touch and route changes, at most one ping a minute with a trailing ping", async () => {
    const browser = scripted();
    const view = render(<SessionWatch />);
    await flush();
    expect(pings(browser.calls)).toBe(1);
    await advance(10_000);
    fireEvent.pointerDown(window);
    expect(Number(localStorage.getItem(KEYS.activity))).toBe(Date.now());
    await advance(5000);
    fireEvent.keyDown(window, { key: "a" });
    fireEvent.wheel(window);
    fireEvent.touchStart(window);
    await flush();
    expect(pings(browser.calls)).toBe(1); // inside the window
    await advance(MIN);
    expect(pings(browser.calls)).toBe(2); // the trailing ping
    await advance(5 * MIN);
    expect(pings(browser.calls)).toBe(2); // quiet
    nav.pathname = "/alerts";
    view.rerender(<SessionWatch />);
    await flush();
    expect(Number(localStorage.getItem(KEYS.activity))).toBe(Date.now());
    expect(pings(browser.calls)).toBe(3); // leading edge: the last ping is a minute old
  });

  it("pauses the page's listeners while the warning is open", async () => {
    scripted();
    render(<SessionWatch />);
    await flush();
    await advance(28 * MIN);
    const activity = localStorage.getItem(KEYS.activity);
    fireEvent.wheel(window);
    fireEvent.pointerDown(document.body);
    await advance(1000);
    expect(localStorage.getItem(KEYS.activity)).toBe(activity);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes the open warning when another tab writes newer activity", async () => {
    scripted();
    render(<SessionWatch />);
    await flush();
    await advance(28 * MIN + 3000);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    localStorage.setItem(KEYS.activity, String(Date.now()));
    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: KEYS.activity }));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("follows another tab's out without calling the API", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    await advance(5000);
    localStorage.setItem(KEYS.out, JSON.stringify({ reason: "signed_out", at: Date.now() }));
    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: KEYS.out }));
    });
    expect(navigate).toHaveBeenCalledWith("/login?reason=signed_out&next=%2Fcases%2Fx");
    expect(clearCache).toHaveBeenCalled();
    expect(browser.calls.some((c) => c.path === "session:/logout")).toBe(false);
  });

  it("ignores an out written before the page was opened", async () => {
    localStorage.setItem(KEYS.out, JSON.stringify({ reason: "idle", at: T0 - MIN }));
    scripted();
    render(<SessionWatch />);
    await flush();
    await advance(3000);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("signs out on the first tick after a 31-minute jump of the clock (sleep and wake)", async () => {
    const browser = scripted();
    render(<SessionWatch />);
    await flush();
    vi.setSystemTime(T0 + 31 * MIN);
    await advance(1000);
    await flush();
    expect(navigate).toHaveBeenCalledWith("/login?reason=idle&next=%2Fcases%2Fx");
    expect(logoutBodies(browser.calls)).toEqual([{ reason: "idle" }]);
  });

  it("shows the 12-hour notice: Continue closes it, Sign in Now signs out to /login?next=", async () => {
    const browser = scripted({ ...DEFAULT_PING, session_ends_in: 125 });
    render(<SessionWatch />);
    await flush();
    await advance(5000);
    expect(screen.getByRole("dialog", { name: "Session Ending Soon" })).toBeInTheDocument();
    expect(screen.getByText(/reaches its 12-hour limit in 2:00/)).toBeInTheDocument(); // max_hours from the ping
    expect(screen.queryByRole("button", { name: "Stay Signed In" })).toBeNull();
    expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await advance(1000);
    expect(screen.queryByRole("dialog")).toBeNull();
    await advance(MIN);
    expect(screen.queryByRole("dialog")).toBeNull(); // dismissed for this session
    await advance(MIN);
    expect(navigate).toHaveBeenCalledWith("/login?reason=limit&next=%2Fcases%2Fx");
    expect(logoutBodies(browser.calls)).toEqual([{ reason: "limit" }]);
  });

  it("Sign in Now signs out every tab and goes to the sign-in page", async () => {
    const browser = scripted({ ...DEFAULT_PING, session_ends_in: 100 });
    render(<SessionWatch />);
    await flush();
    await advance(1000);
    fireEvent.click(screen.getByRole("button", { name: "Sign in Now" }));
    await flush();
    expect(JSON.parse(localStorage.getItem(KEYS.out)!)).toMatchObject({ reason: "signed_out" });
    expect(logoutBodies(browser.calls)).toEqual([{}]); // a real sign-out: the API is told
    expect(navigate).toHaveBeenCalledWith("/login?next=%2Fcases%2Fx");
  });

  it("keeps the clock in memory when localStorage throws, and still warns", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    resetSessionStore();
    expect(sessionStore().persistent).toBe(false);
    scripted();
    render(<SessionWatch />);
    await flush();
    await advance(28 * MIN);
    expect(screen.getByRole("dialog", { name: "Are You Still There?" })).toBeInTheDocument();
  });
});

describe("the session store", () => {
  it("falls back to memory and keeps one tab's state", () => {
    const store = createStore(null);
    expect(store.persistent).toBe(false);
    store.setActivity(5);
    store.setOut("limit", 9);
    expect(store.activity()).toBe(5);
    expect(store.out()).toEqual({ reason: "limit", at: 9 });
    expect(store.limits().idleMs).toBe(30 * MIN);
  });

  it("drops a hard end already past", () => {
    const store = createStore();
    store.setLimits({ idleMs: 30 * MIN, warningMs: 2 * MIN, hardEnd: T0 - 1, maxHours: 12 });
    store.dropPastHardEnd(T0);
    expect(store.limits().hardEnd).toBeNull();
    expect(store.storedLimits()).toEqual({ idle_seconds: 1800, warning_seconds: 120, hard_end: null, max_hours: 12 });
  });

  it("forgets the limits on clearLimits", () => {
    const store = createStore();
    store.setLimits({ idleMs: 30 * MIN, warningMs: 2 * MIN, hardEnd: T0 + MIN, maxHours: 12 });
    store.clearLimits();
    expect(store.storedLimits()).toBeNull();
    expect(localStorage.getItem(KEYS.limits)).toBeNull();
  });
});
