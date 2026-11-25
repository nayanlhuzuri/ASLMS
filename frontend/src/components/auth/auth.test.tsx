import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ARRIVE_KEY } from "@/components/shell/arrive";
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

describe("sign-in", () => {
  it("locked shows the wait from retry_after", async () => {
    browserApi({
      "POST session:/login": json(429, { detail: { code: "locked", message: "x", retry_after: 300 } }),
    });
    renderWithClient(<LoginForm onSent={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "a@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 5 minutes");
  });

  it("mail_not_configured says mail is unavailable", async () => {
    browserApi({
      "POST session:/login": json(503, { detail: { code: "mail_not_configured", message: "x" } }),
    });
    renderWithClient(<LoginForm onSent={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "a@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Contact the administrator");
  });

  it("the resend button stays disabled until resend_after has passed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    saveStep({ sent_to: "a***@example.org", expires_in: 600, resend_after: 3 });
    browserApi({});
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
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
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("2 attempts left");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("an expired code clears the step and hands back to the card, with no navigation of its own", async () => {
    saveStep({ sent_to: "a***", resend_after: 0 });
    browserApi({ "POST session:/verify": json(401, { detail: { code: "otp_expired", message: "x" } }) });
    const onExpired = vi.fn();
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={onExpired} />);
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(onExpired).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem("aslms.step")).toBeNull();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("Start Again keeps its address for no-script use and hands back to the card on a click", async () => {
    resetNav("/login", "step=code&next=/alerts");
    const onStartAgain = vi.fn();
    renderWithClient(<CodeForm onStartAgain={onStartAgain} onExpired={vi.fn()} />);
    const link = screen.getByRole("link", { name: "Start Again" });
    expect(link).toHaveAttribute("href", "/login?next=%2Falerts");
    await userEvent.click(link);
    expect(onStartAgain).toHaveBeenCalledTimes(1);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("the code field is described by the sentence naming where the code went", () => {
    saveStep({ sent_to: "a***@example.org", resend_after: 0 });
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    expect(screen.getByLabelText("Code")).toHaveAccessibleDescription("A 6-digit code was sent to a***@example.org.");
  });

  it("the heading level follows the place: h1 by default, h2 in the home page's card", () => {
    const { unmount } = renderWithClient(<LoginForm onSent={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Sign In" })).toBeInTheDocument();
    unmount();
    renderWithClient(<CodeForm headingLevel="h2" onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2, name: "Enter the Code" })).toBeInTheDocument();
  });

  it.each([
    ["ready", "/admin/users"],
    ["change_password", "/welcome/password?next=%2Fadmin%2Fusers"],
    ["confirm_profile", "/welcome/profile?next=%2Fadmin%2Fusers"],
  ])("next_step %s routes to %s", async (step, target) => {
    resetNav("/login/code", "next=/admin/users");
    browserApi({ "POST session:/verify": { next_step: step, user: {} } });
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(target));
    // design home-page, decision 13: the portal fades in once; the first-sign-in pages have their own entry
    expect(sessionStorage.getItem(ARRIVE_KEY)).toBe(step === "ready" ? "1" : null);
  });

  it("a successful code clears the previous session's stored limits (review finding 2)", async () => {
    localStorage.setItem(
      KEYS.limits,
      JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: Date.now() + 60_000, max_hours: 12 }),
    );
    resetSessionStore();
    resetNav("/login/code");
    browserApi({ "POST session:/verify": { next_step: "ready", user: {} } });
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem(KEYS.limits)).toBeNull();
  });

  it("a refused code keeps them", async () => {
    localStorage.setItem(KEYS.limits, JSON.stringify({ idle_seconds: 1800, warning_seconds: 120, hard_end: null }));
    resetSessionStore();
    browserApi({ "POST session:/verify": json(401, { detail: { code: "otp_invalid", message: "x", attempts_left: 2 } }) });
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await screen.findByRole("alert");
    expect(localStorage.getItem(KEYS.limits)).not.toBeNull();
  });

  it("an unsafe next is ignored", async () => {
    resetNav("/login/code", "next=//evil.example");
    browserApi({ "POST session:/verify": { next_step: "ready", user: {} } });
    renderWithClient(<CodeForm onStartAgain={vi.fn()} onExpired={vi.fn()} />);
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
