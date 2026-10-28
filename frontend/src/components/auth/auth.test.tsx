import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KEYS, resetSessionStore } from "@/lib/session/store";
import { browserApi, json, labels, renderWithClient } from "@/test/render";
import { nav, resetNav } from "@/test/nav";

import { CodeForm, ForgotForm, LoginForm } from "./SignInForms";
import { saveStep } from "./steps";
import { PasswordStepForm, ProfileStepForm } from "./WelcomeForms";

beforeEach(() => {
  resetNav("/login");
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the sign-in page after a sign-out (design session-timeout, decision 20)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetSessionStore();
  });

  it("explains an idle sign-out with the minutes from the shared clock", () => {
    localStorage.setItem(KEYS.limits, JSON.stringify({ idle_seconds: 180, warning_seconds: 60, hard_end: null }));
    resetNav("/login", "reason=idle&next=/alerts&minutes=999");
    renderWithClient(<LoginForm />);
    expect(screen.getByText("You were signed out after 3 minutes without activity.")).toBeInTheDocument();
    expect(screen.queryByText(/999/)).toBeNull();
  });

  it("without the shared clock it says a period without activity", () => {
    resetNav("/login", "reason=idle");
    renderWithClient(<LoginForm />);
    expect(screen.getByText("You were signed out after a period without activity.")).toBeInTheDocument();
  });

  it("names the hard limit's hours from the shared clock", () => {
    localStorage.setItem(
      KEYS.limits,
      JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: null, max_hours: 8 }),
    );
    resetNav("/login", "reason=limit&hours=99");
    renderWithClient(<LoginForm />);
    expect(screen.getByText("Your session reached its 8-hour limit. Sign in again.")).toBeInTheDocument();
  });

  it.each([
    ["limit", "Your session reached its time limit. Sign in again."],
    ["signed_out", "You signed out."],
  ])("reason=%s shows its banner", (reason, text) => {
    resetNav("/login", `reason=${reason}`);
    renderWithClient(<LoginForm />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("an unknown reason shows nothing", () => {
    resetNav("/login", "reason=<script>");
    const { container } = renderWithClient(<LoginForm />);
    expect(container.textContent).not.toContain("signed out");
    expect(container.textContent).not.toContain("script");
  });
});

describe("sign-in", () => {
  it("the password step leads to the code step and keeps next", async () => {
    resetNav("/login", "next=/admin/users");
    const api = browserApi({
      "POST session:/login": { step: "otp", purpose: "login", sent_to: "a***@example.org", expires_in: 600, resend_after: 120 },
    });
    renderWithClient(<LoginForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "anita@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/login/code?next=%2Fadmin%2Fusers"));
    expect(api.calls[0]!.body).toEqual({ email: "anita@example.org", password: "secret-pass-1" });
    expect(JSON.parse(sessionStorage.getItem("aslms.step")!)).toMatchObject({ sent_to: "a***@example.org" });
  });

  it("locked shows the wait from retry_after", async () => {
    browserApi({
      "POST session:/login": json(429, { detail: { code: "locked", message: "x", retry_after: 300 } }),
    });
    renderWithClient(<LoginForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "a@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 5 minutes");
  });

  it("mail_not_configured says mail is unavailable", async () => {
    browserApi({
      "POST session:/login": json(503, { detail: { code: "mail_not_configured", message: "x" } }),
    });
    renderWithClient(<LoginForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "a@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Contact the administrator");
  });

  it("the resend button stays disabled until resend_after has passed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    saveStep({ sent_to: "a***@example.org", expires_in: 600, resend_after: 3 });
    browserApi({});
    renderWithClient(<CodeForm />);
    expect(screen.getByText("A 6-digit code was sent to a***@example.org.")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Send a New Code in 3 s" });
    expect(button).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole("button", { name: "Send a New Code in 2 s" })).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("button", { name: "Send a New Code" })).toBeEnabled();
  });

  it("a wrong code shows attempts_left", async () => {
    saveStep({ sent_to: "a***", resend_after: 0 });
    browserApi({
      "POST session:/verify": json(401, { detail: { code: "otp_invalid", message: "x", attempts_left: 2 } }),
    });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("2 attempt(s) left");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("an expired code goes back to the password step", async () => {
    browserApi({ "POST session:/verify": json(401, { detail: { code: "otp_expired", message: "x" } }) });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?expired=1"));
  });

  it.each([
    ["ready", "/admin/users"],
    ["change_password", "/welcome/password?next=%2Fadmin%2Fusers"],
    ["confirm_profile", "/welcome/profile?next=%2Fadmin%2Fusers"],
  ])("next_step %s routes to %s", async (step, target) => {
    resetNav("/login/code", "next=/admin/users");
    browserApi({ "POST session:/verify": { next_step: step, user: {} } });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(target));
  });

  it("a successful code clears the previous session's stored limits (review finding 2)", async () => {
    localStorage.setItem(
      KEYS.limits,
      JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: Date.now() + 60_000, max_hours: 12 }),
    );
    resetSessionStore();
    resetNav("/login/code");
    browserApi({ "POST session:/verify": { next_step: "ready", user: {} } });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem(KEYS.limits)).toBeNull();
  });

  it("a refused code keeps them", async () => {
    localStorage.setItem(KEYS.limits, JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: null }));
    resetSessionStore();
    browserApi({ "POST session:/verify": json(401, { detail: { code: "otp_invalid", message: "x", attempts_left: 2 } }) });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await screen.findByRole("alert");
    expect(localStorage.getItem(KEYS.limits)).not.toBeNull();
  });

  it("an unsafe next is ignored", async () => {
    resetNav("/login/code", "next=//evil.example");
    browserApi({ "POST session:/verify": { next_step: "ready", user: {} } });
    renderWithClient(<CodeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
  });

  it("the forgotten-password request moves on whatever the account", async () => {
    browserApi({ "POST session:/reset/request": json(202, { expires_in: 600, resend_after: 120 }) });
    renderWithClient(<ForgotForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "nobody@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Send Code" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/forgot/code"));
  });
});

describe("first sign-in", () => {
  it("the password form shows the policy and the server's weak_password message", async () => {
    browserApi({
      "POST session:/password": json(422, {
        detail: { code: "weak_password", message: "the password needs at least one digit" },
      }),
    });
    renderWithClient(<PasswordStepForm />);
    expect(screen.getAllByText("At least 10 characters, with a letter and a digit.").length).toBeGreaterThan(0);
    await userEvent.type(screen.getByLabelText("Current Password"), "temporary-1");
    await userEvent.type(screen.getByLabelText("New Password"), "abcdefghijk");
    await userEvent.type(screen.getByLabelText("Repeat the New Password"), "abcdefghijk");
    await userEvent.click(screen.getByRole("button", { name: "Set Password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the password needs at least one digit");
  });

  it("the password form follows next_step to the profile", async () => {
    browserApi({ "POST session:/password": { next_step: "confirm_profile" } });
    renderWithClient(<PasswordStepForm />);
    await userEvent.type(screen.getByLabelText("Current Password"), "temporary-1");
    await userEvent.type(screen.getByLabelText("New Password"), "a-better-pass-1");
    await userEvent.type(screen.getByLabelText("Repeat the New Password"), "a-better-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Set Password" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/welcome/profile"));
  });

  it("the profile confirmation requires the mobile number", async () => {
    const api = browserApi({
      "GET /me/profile": {
        email: "anita@example.org",
        full_name: "Anita Sharma",
        mobile: null,
        must_change_password: false,
        must_confirm_profile: true,
        profile_confirmed_at: null,
        memberships: [{ office: { code: "EDU", name: "Education", kind: "department" }, designation: "US", role: "dept_officer", is_primary: true }],
        notification_preferences: { email: { enabled: true, critical_only: false, digest: "daily" }, in_app: { enabled: true }, sms: { available: false } },
      },
      "GET /reference/labels": labels(),
      "POST /me/profile/confirm": { ok: true },
    });
    renderWithClient(<ProfileStepForm />);
    const confirm = await screen.findByRole("button", { name: "Confirm and Continue" });
    await userEvent.click(confirm);
    expect(await screen.findByText("A mobile number is required.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/me/profile/confirm")).toBe(false);
    fireEvent.change(screen.getByLabelText("Mobile Number"), { target: { value: "98640 12345" } });
    await userEvent.click(confirm);
    await waitFor(() => expect(api.calls.some((c) => c.path === "/me/profile/confirm")).toBe(true));
    const sent = api.calls.find((c) => c.path === "/me/profile/confirm")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ full_name: "Anita Sharma", mobile: "9864012345" });
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
  });
});
