/**
 * The public pages' frame and the error pages (design portal-ui-redesign, round 5; decision 26 as amended on 20 Oct
 * 2026: template A, the split panel): the brand on every public page, the panel's texts, the two-step indicator, the
 * show-password button, and the error and not-found pages on the empty-state pattern with the brand.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ErrorPage from "@/app/error";
import NotFound from "@/app/not-found";
import PublicLayout from "@/app/(public)/layout";
import WelcomeLayout from "@/app/(welcome)/layout";
import { BRAND } from "@/lib/brand";
import { T } from "@/lib/messages";
import { resetNav } from "@/test/nav";
import { primaryActions, renderWithClient } from "@/test/render";

import { CodeForm, ForgotCodeForm, ForgotForm, LoginForm } from "./SignInForms";
import { PasswordStepForm } from "./WelcomeForms";

beforeEach(() => {
  resetNav("/login");
  sessionStorage.clear();
});

describe("the public pages' frame (template A)", () => {
  it.each([
    ["sign-in", <LoginForm key="l" />],
    ["code", <CodeForm key="c" />],
    ["reset", <ForgotForm key="f" />],
    ["reset code", <ForgotCodeForm key="fc" />],
  ])("the %s page shows the official emblem, the panel and one primary", (_name, form) => {
    const { container } = renderWithClient(<PublicLayout>{form}</PublicLayout>);
    const brand = screen.getByTestId("auth-brand");
    const img = within(brand).getByRole("img", { name: T.brand.emblemAlt });
    expect(img).toHaveAttribute("src", BRAND.lockup!.src);
    expect(within(brand).getByText(T.portal)).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: T.auth.frame.label });
    expect(within(panel).getByText(T.owner)).toBeInTheDocument();
    expect(within(panel).getByText(T.portalLong)).toBeInTheDocument();
    expect(within(panel).getByText(T.auth.frame.lead)).toBeInTheDocument();
    for (const tile of T.auth.frame.tiles) expect(within(panel).getByText(tile.title)).toBeInTheDocument();
    expect(screen.getByText(T.auth.frame.foot)).toBeInTheDocument();
    // the court is not named on these pages
    expect(container.textContent).not.toContain(T.court);
    expect(primaryActions(container)).toHaveLength(1);
  });

  it("the first-sign-in pages use the same frame with the wider form side", () => {
    const { container } = renderWithClient(
      <WelcomeLayout>
        <PasswordStepForm />
      </WelcomeLayout>,
    );
    expect(within(screen.getByTestId("auth-brand")).getByRole("img", { name: T.brand.emblemAlt })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: T.auth.welcomePasswordTitle }).closest("form")!.parentElement!.className).toMatch(/wide/);
    expect(primaryActions(container)).toHaveLength(1);
  });

  it("the sign-in shows step 1 of 2 with its line, the code page step 2", () => {
    const { unmount } = renderWithClient(<LoginForm />);
    expect(screen.getByText(`${T.auth.stepOf(1, 2)}.`, { exact: false })).toBeInTheDocument();
    expect(screen.getByText(T.auth.steps)).toBeInTheDocument();
    expect(screen.getByText(T.auth.signInSub)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: T.auth.forgot })).toHaveAttribute("href", "/forgot");
    unmount();
    renderWithClient(<CodeForm />);
    expect(screen.getByText(`${T.auth.stepOf(2, 2)}.`, { exact: false })).toBeInTheDocument();
  });

  it("the password field has the show / hide button", async () => {
    renderWithClient(<LoginForm />);
    const field = screen.getByLabelText(T.auth.password);
    expect(field).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: T.showPassword }));
    expect(field).toHaveAttribute("type", "text");
  });
});

describe("the error pages (empty-state pattern with the brand)", () => {
  it("the error page names the problem, offers Try again as its one primary and the way home", async () => {
    const reset = vi.fn();
    const { container } = render(<ErrorPage error={new Error("boom")} reset={reset} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: T.errorTitle })).toBeInTheDocument();
    expect(screen.getByText(T.errorText)).toBeInTheDocument();
    expect(screen.getByText(T.owner)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: T.goHome })).toHaveAttribute("href", "/");
    expect(primaryActions(container)).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: T.retry }));
    expect(reset).toHaveBeenCalled();
    expect(container.textContent).not.toContain("boom");
  });

  it("the not-found page names the page and links home", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: T.notFound })).toBeInTheDocument();
    expect(screen.getByText(T.notFoundText)).toBeInTheDocument();
    expect(screen.getByText(T.owner)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: T.goHome })).toHaveAttribute("href", "/");
  });
});
