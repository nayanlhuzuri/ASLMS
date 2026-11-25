/**
 * The home page's sign-in card (design home-page, decisions 2, 12 and 13): the step from the address, the change of
 * step in place with `history.pushState` (never `router.push`), the cross-fade with the outgoing step inert, the
 * instant swap under reduced motion, Back, the expired code and Start Again, the arrival flag after the code, and the
 * password step's notices (the earlier `LoginForm` cases, moved here).
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ARRIVE_KEY } from "@/components/shell/arrive";
import { saveStep } from "@/components/auth/steps";
import { DURATION } from "@/components/ui/motion";
import { KEYS, resetSessionStore } from "@/lib/session/store";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, renderWithClient } from "@/test/render";

import { SignInCard, stepAddress } from "./SignInCard";

const LOGIN_OK = { step: "otp", purpose: "login", sent_to: "a***@example.org", expires_in: 600, resend_after: 120 };

/** The computer's motion setting as `matchMedia` answers it (jsdom has none, which reads as reduced motion). */
function motion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("reduce") ? reduced : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

/**
 * The history calls recorded, and the mocked address following them, as Next.js keeps `useSearchParams` in step with
 * `pushState` and `replaceState` in the browser.
 */
function trackHistory() {
  const follow = (url: string | URL | null | undefined) => {
    nav.search = new URLSearchParams(String(url ?? "").split("?")[1] ?? "");
  };
  const push = vi.spyOn(window.history, "pushState").mockImplementation((_s, _t, url) => follow(url));
  const replace = vi.spyOn(window.history, "replaceState").mockImplementation((_s, _t, url) => follow(url));
  return { push, replace };
}

function steps(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("[data-step]")];
}

async function signIn() {
  await userEvent.type(screen.getByLabelText("E-mail"), "anita@example.org");
  await userEvent.type(screen.getByLabelText("Password"), "secret-pass-1");
  await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
}

beforeEach(() => {
  resetNav("/login");
  sessionStorage.clear();
  localStorage.clear();
  resetSessionStore();
});

describe("the step's address", () => {
  it("keeps next and expired, and is /login on its own", () => {
    expect(stepAddress("password", "/")).toBe("/login");
    expect(stepAddress("code", "/")).toBe("/login?step=code");
    expect(stepAddress("code", "/admin/users")).toBe("/login?step=code&next=%2Fadmin%2Fusers");
    expect(stepAddress("password", "/alerts", true)).toBe("/login?expired=1&next=%2Falerts");
  });
});

describe("the sign-in card (design home-page, decision 12)", () => {
  it("the password step leads to the code step in place, with pushState and never router.push", async () => {
    motion(true);
    resetNav("/login", "next=/admin/users");
    const history = trackHistory();
    const api = browserApi({ "POST session:/login": LOGIN_OK });
    renderWithClient(<SignInCard />);
    await signIn();
    expect(await screen.findByRole("heading", { level: 2, name: "Enter the Code" })).toBeInTheDocument();
    expect(history.push).toHaveBeenCalledWith(null, "", "/login?step=code&next=%2Fadmin%2Fusers");
    expect(nav.push).not.toHaveBeenCalled();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(api.calls[0]!.body).toEqual({ email: "anita@example.org", password: "secret-pass-1" });
    const code = screen.getByLabelText("Code");
    await waitFor(() => expect(code).toHaveFocus());
    expect(code).toHaveAccessibleDescription("A 6-digit code was sent to a***@example.org.");
  });

  it("the outgoing step is inert and hidden while it fades, then only the new one remains", async () => {
    motion(false);
    trackHistory();
    browserApi({ "POST session:/login": LOGIN_OK });
    renderWithClient(<SignInCard />);
    expect(steps().map((s) => s.dataset.step)).toEqual(["password"]);
    // the first load does not animate
    expect(steps()[0]).not.toHaveAttribute("data-phase");
    await signIn();
    await screen.findByRole("heading", { name: "Enter the Code" });
    const [outgoing, incoming] = steps();
    expect(outgoing!.dataset.step).toBe("password");
    expect(outgoing).toHaveAttribute("inert");
    expect(outgoing).toHaveAttribute("aria-hidden", "true");
    expect(outgoing).toHaveAttribute("data-phase", "leave");
    expect(incoming!.dataset.step).toBe("code");
    expect(incoming).not.toHaveAttribute("inert");
    expect(incoming).toHaveAttribute("data-phase", "enter");
    expect(incoming).toHaveAttribute("data-dir", "forward");
    await waitFor(() => expect(steps().map((s) => s.dataset.step)).toEqual(["code"]), { timeout: DURATION.med * 4 });
    expect(screen.getByLabelText("Code")).toHaveFocus();
  });

  it("under reduced motion the steps swap at once: only one is ever mounted", async () => {
    motion(true);
    trackHistory();
    browserApi({ "POST session:/login": LOGIN_OK });
    renderWithClient(<SignInCard />);
    await signIn();
    await screen.findByRole("heading", { name: "Enter the Code" });
    expect(steps().map((s) => s.dataset.step)).toEqual(["code"]);
  });

  it("Back returns to the password step and focuses the e-mail field", async () => {
    motion(true);
    trackHistory();
    browserApi({ "POST session:/login": LOGIN_OK });
    const { rerender } = renderWithClient(<SignInCard />);
    await signIn();
    await screen.findByRole("heading", { name: "Enter the Code" });
    // the browser's Back: the address loses its step
    nav.search = new URLSearchParams("");
    rerender(<SignInCard />);
    expect(await screen.findByRole("heading", { level: 2, name: "Sign In" })).toBeInTheDocument();
    expect(steps().map((s) => s.dataset.step)).toEqual(["password"]);
    await waitFor(() => expect(screen.getByLabelText("E-mail")).toHaveFocus());
    expect(steps()[0]).toHaveAttribute("data-dir", "back");
  });

  it("Back during the fade brings back a password step that is not busy (review advisory)", async () => {
    motion(false);
    trackHistory();
    browserApi({ "POST session:/login": LOGIN_OK });
    const { rerender } = renderWithClient(<SignInCard />);
    await signIn();
    await screen.findByRole("heading", { name: "Enter the Code" });
    // still inside the fade: the same password form is mounted, leaving
    const outgoing = steps()[0]!;
    expect(outgoing.dataset.step).toBe("password");
    expect(outgoing).toHaveAttribute("data-phase", "leave");
    nav.search = new URLSearchParams("");
    rerender(<SignInCard />);
    // the same instance returns (no remount), with its button ready again
    expect(steps()[0]).toBe(outgoing);
    expect(outgoing).not.toHaveAttribute("inert");
    const button = screen.getByRole("button", { name: "Sign In" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-busy");
    expect(screen.queryByText("Signing In…")).toBeNull();
  });

  it("?step=code on load shows the code step, with the general sentence when nothing is stored", () => {
    motion(true);
    resetNav("/login", "step=code");
    renderWithClient(<SignInCard />);
    expect(screen.getByRole("heading", { level: 2, name: "Enter the Code" })).toBeInTheDocument();
    expect(screen.getByText("A 6-digit code was sent to your e-mail.")).toBeInTheDocument();
    // a load is not a change: no animation and no focus taken
    expect(steps()[0]).not.toHaveAttribute("data-phase");
    expect(screen.getByLabelText("Code")).not.toHaveFocus();
  });

  it("an expired code returns to the password step with the banner, by replaceState keeping next", async () => {
    motion(true);
    resetNav("/login", "step=code&next=/alerts");
    const history = trackHistory();
    browserApi({ "POST session:/verify": json(401, { detail: { code: "otp_expired", message: "x" } }) });
    renderWithClient(<SignInCard />);
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Sign In" })).toBeInTheDocument();
    expect(history.replace).toHaveBeenCalledWith(null, "", "/login?expired=1&next=%2Falerts");
    expect(screen.getByRole("alert")).toHaveTextContent("The code has expired. Start again.");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("Start Again goes back to the password step with pushState, keeping next", async () => {
    motion(true);
    resetNav("/login", "step=code&next=/alerts");
    const history = trackHistory();
    renderWithClient(<SignInCard />);
    await userEvent.click(screen.getByRole("link", { name: "Start Again" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Sign In" })).toBeInTheDocument();
    expect(history.push).toHaveBeenCalledWith(null, "", "/login?next=%2Falerts");
    expect(nav.push).not.toHaveBeenCalled();
  });

  it.each([
    ["ready", "", "/", "1"],
    ["ready", "next=/admin/users", "/admin/users", "1"],
    ["change_password", "", "/welcome/password", null],
  ])("after the code (%s, %s) the portal opens with router.replace and the arrival flag where it fades", async (step, query, target, flag) => {
    motion(true);
    resetNav("/login", `step=code${query ? `&${query}` : ""}`);
    saveStep({ sent_to: "a***", resend_after: 0 });
    browserApi({ "POST session:/verify": { next_step: step, user: {} } });
    renderWithClient(<SignInCard />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(target));
    expect(sessionStorage.getItem(ARRIVE_KEY)).toBe(flag);
  });
});

describe("the password step's notices (design session-timeout, decision 20; the LoginForm cases, moved)", () => {
  beforeEach(() => motion(true));

  it("explains an idle sign-out with the minutes from the shared clock, never from the address", () => {
    localStorage.setItem(KEYS.limits, JSON.stringify({ idle_seconds: 180, warning_seconds: 60, hard_end: null }));
    resetNav("/login", "reason=idle&next=/alerts&minutes=999");
    renderWithClient(<SignInCard />);
    expect(screen.getByText("You were signed out after 3 minutes without activity.")).toBeInTheDocument();
    expect(screen.queryByText(/999/)).toBeNull();
  });

  it("without the shared clock it says a period without activity", () => {
    resetNav("/login", "reason=idle");
    renderWithClient(<SignInCard />);
    expect(screen.getByText("You were signed out after a period without activity.")).toBeInTheDocument();
  });

  it("names the hard limit's hours from the shared clock", () => {
    localStorage.setItem(KEYS.limits, JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: null, max_hours: 8 }));
    resetNav("/login", "reason=limit&hours=99");
    renderWithClient(<SignInCard />);
    expect(screen.getByText("Your session reached its 8-hour limit. Sign in again.")).toBeInTheDocument();
  });

  it.each([
    ["limit", "Your session reached its time limit. Sign in again."],
    ["signed_out", "You signed out."],
  ])("reason=%s shows its banner", (reason, text) => {
    resetNav("/login", `reason=${reason}`);
    renderWithClient(<SignInCard />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("an unknown reason shows nothing", () => {
    resetNav("/login", "reason=<script>");
    const { container } = renderWithClient(<SignInCard />);
    expect(container.textContent).not.toContain("signed out");
    expect(container.textContent).not.toContain("script");
  });

  it("?expired=1 shows the expired banner and ?reset=done the password-changed notice", () => {
    resetNav("/login", "expired=1");
    const { unmount } = renderWithClient(<SignInCard />);
    expect(screen.getByRole("alert")).toHaveTextContent("The code has expired. Start again.");
    unmount();
    resetNav("/login", "reset=done");
    renderWithClient(<SignInCard />);
    expect(screen.getByText("Password changed. Sign in with the new password.")).toBeInTheDocument();
  });
});
