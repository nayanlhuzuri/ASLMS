import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  it("the password step leads to the code step and keeps next", async () => {
    resetNav("/login", "next=/admin/users");
    const api = browserApi({
      "POST session:/login": { step: "otp", purpose: "login", sent_to: "a***@example.org", expires_in: 600, resend_after: 120 },
    });
    renderWithClient(<LoginForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "anita@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 5 minutes");
  });

  it("mail_not_configured says mail is unavailable", async () => {
    browserApi({
      "POST session:/login": json(503, { detail: { code: "mail_not_configured", message: "x" } }),
    });
    renderWithClient(<LoginForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "a@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Contact the administrator");
  });

  it("the resend button stays disabled until resend_after has passed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    saveStep({ sent_to: "a***@example.org", expires_in: 600, resend_after: 3 });
    browserApi({});
    renderWithClient(<CodeForm />);
    expect(screen.getByText("A 6-digit code was sent to a***@example.org.")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Send a new code in 3 s" });
    expect(button).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole("button", { name: "Send a new code in 2 s" })).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("button", { name: "Send a new code" })).toBeEnabled();
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
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
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
    await userEvent.type(screen.getByLabelText("Current password"), "temporary-1");
    await userEvent.type(screen.getByLabelText("New password"), "abcdefghijk");
    await userEvent.type(screen.getByLabelText("Repeat the new password"), "abcdefghijk");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the password needs at least one digit");
  });

  it("the password form follows next_step to the profile", async () => {
    browserApi({ "POST session:/password": { next_step: "confirm_profile" } });
    renderWithClient(<PasswordStepForm />);
    await userEvent.type(screen.getByLabelText("Current password"), "temporary-1");
    await userEvent.type(screen.getByLabelText("New password"), "a-better-pass-1");
    await userEvent.type(screen.getByLabelText("Repeat the new password"), "a-better-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
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
    const confirm = await screen.findByRole("button", { name: "Confirm and continue" });
    await userEvent.click(confirm);
    expect(await screen.findByText("A mobile number is required.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/me/profile/confirm")).toBe(false);
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "98640 12345" } });
    await userEvent.click(confirm);
    await waitFor(() => expect(api.calls.some((c) => c.path === "/me/profile/confirm")).toBe(true));
    const sent = api.calls.find((c) => c.path === "/me/profile/confirm")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ full_name: "Anita Sharma", mobile: "9864012345" });
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
  });
});
