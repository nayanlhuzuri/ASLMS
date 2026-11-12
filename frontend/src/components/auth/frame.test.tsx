/**
 * The public pages' frame and the error pages (design portal-ui-redesign, round 5; decision 26 as amended on 20 Oct
 * 2026: template A, the split panel; amended by design signin-gold-emblem, row 249): the gold Lion Capital at the top
 * of the panel with its two lines and its Pause / Play button, no brand row on the form side, the panel's texts, the
 * two-step indicator, the show-password button, and the error and not-found pages on the empty-state pattern with the
 * brand.
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

import { EMBLEM_MOTION_KEY, GoldEmblem } from "./GoldEmblem";
import { CodeForm, ForgotCodeForm, ForgotForm, LoginForm } from "./SignInForms";
import { PasswordStepForm } from "./WelcomeForms";

const E = T.auth.frame.emblem;

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

function panel(): HTMLElement {
  return screen.getByRole("region", { name: T.auth.frame.label });
}

function emblem(): HTMLElement {
  return within(panel()).getByRole("img", { name: T.brand.emblemAlt });
}

/** The block the paused state marks: the emblem's parent (looked up on the whole page, so it works without a frame). */
function emblemBlock(): HTMLElement {
  return screen.getByRole("img", { name: T.brand.emblemAlt }).parentElement!;
}

beforeEach(() => {
  resetNav("/login");
  sessionStorage.clear();
  localStorage.clear();
  motion(false);
});

describe("the public pages' frame (template A with the gold emblem)", () => {
  it.each([
    ["sign-in", <LoginForm key="l" />],
    ["code", <CodeForm key="c" />],
    ["reset", <ForgotForm key="f" />],
    ["reset code", <ForgotCodeForm key="fc" />],
  ])("the %s page shows the gold emblem in the panel, the panel's texts and one primary", (_name, form) => {
    const { container } = renderWithClient(<PublicLayout>{form}</PublicLayout>);
    const region = panel();
    expect(within(region).getAllByRole("img", { name: T.brand.emblemAlt })).toHaveLength(1);
    // the stage is masked by the official cut-out configured in brand.ts
    const stage = emblem().querySelector<HTMLElement>("[style]")!;
    expect(stage.style.getPropertyValue("--emblem-mask")).toContain(BRAND.capital!.src);
    expect(within(region).getByText(T.owner)).toBeInTheDocument();
    expect(within(region).getByText(T.portalLong)).toBeInTheDocument();
    expect(within(region).getByText(T.auth.frame.lead)).toBeInTheDocument();
    for (const tile of T.auth.frame.tiles) expect(within(region).getByText(tile.title)).toBeInTheDocument();
    expect(screen.getByText(T.auth.frame.foot)).toBeInTheDocument();
    // the court is not named on these pages
    expect(container.textContent).not.toContain(T.court);
    expect(primaryActions(container)).toHaveLength(1);
  });

  it("the brand row is gone: no auth-brand, no image in main, the emblem's label once on the page", () => {
    const { container } = renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    expect(screen.queryByTestId("auth-brand")).toBeNull();
    expect(container.querySelector("main img")).toBeNull();
    expect(within(screen.getByRole("main")).queryByRole("img")).toBeNull();
    expect(screen.getAllByRole("img", { name: T.brand.emblemAlt })).toHaveLength(1);
    expect(screen.getAllByLabelText(T.brand.emblemAlt)).toHaveLength(1);
  });

  it("the form keeps its heading and line", () => {
    const { unmount } = renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    expect(screen.getByRole("heading", { name: T.auth.signIn })).toBeInTheDocument();
    expect(screen.getByText(T.auth.signInSub)).toBeInTheDocument();
    unmount();
    renderWithClient(
      <PublicLayout>
        <CodeForm />
      </PublicLayout>,
    );
    expect(screen.getByRole("heading", { name: T.auth.codeTitle })).toBeInTheDocument();
  });

  it("the two lines come from messages.ts with their languages, inside the emblem and hidden", () => {
    renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    const img = emblem();
    const assamese = within(img).getByText(E.assamese);
    const motto = within(img).getByText(E.motto);
    expect(assamese).toHaveAttribute("lang", "as");
    expect(motto).toHaveAttribute("lang", "sa");
    expect(assamese).toHaveAttribute("aria-hidden", "true");
    expect(motto).toHaveAttribute("aria-hidden", "true");
    for (const child of img.children) expect(child).toHaveAttribute("aria-hidden", "true");
  });

  it("Pause stops the motion and Play restarts it; the button has no aria-pressed and sits outside the emblem", async () => {
    renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    const button = screen.getByRole("button", { name: E.pauseLabel });
    expect(button).toHaveTextContent(E.pause);
    expect(button).not.toHaveAttribute("aria-pressed");
    expect(emblem()).not.toContainElement(button);
    expect(panel()).toContainElement(button);
    expect(emblemBlock()).not.toHaveAttribute("data-motion");
    await userEvent.click(button);
    expect(emblemBlock()).toHaveAttribute("data-motion", "paused");
    expect(button).toHaveAccessibleName(E.playLabel);
    expect(button).toHaveTextContent(E.play);
    expect(button).not.toHaveAttribute("aria-pressed");
    await userEvent.click(button);
    expect(emblemBlock()).not.toHaveAttribute("data-motion");
    expect(button).toHaveAccessibleName(E.pauseLabel);
  });

  it("the pause is remembered on this browser, and the first-sign-in frame starts paused", async () => {
    const { unmount } = renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    await userEvent.click(screen.getByRole("button", { name: E.pauseLabel }));
    expect(localStorage.getItem(EMBLEM_MOTION_KEY)).toBe("paused");
    unmount();
    renderWithClient(
      <WelcomeLayout>
        <PasswordStepForm />
      </WelcomeLayout>,
    );
    expect(emblemBlock()).toHaveAttribute("data-motion", "paused");
    await userEvent.click(screen.getByRole("button", { name: E.playLabel }));
    expect(localStorage.getItem(EMBLEM_MOTION_KEY)).toBeNull();
  });

  it("with localStorage unusable, the button still toggles", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<GoldEmblem />);
    const button = screen.getByRole("button", { name: E.pauseLabel });
    await userEvent.click(button);
    expect(emblemBlock()).toHaveAttribute("data-motion", "paused");
    await userEvent.click(button);
    expect(emblemBlock()).not.toHaveAttribute("data-motion");
  });

  it("reduced motion hides the button and keeps the emblem", () => {
    motion(true);
    renderWithClient(
      <PublicLayout>
        <LoginForm />
      </PublicLayout>,
    );
    expect(screen.queryByRole("button", { name: E.pauseLabel })).toBeNull();
    expect(screen.queryByRole("button", { name: E.playLabel })).toBeNull();
    expect(emblem()).toBeInTheDocument();
  });

  it("with no capital file configured, GoldEmblem renders nothing", () => {
    const { container } = render(<GoldEmblem brand={{ emblem: BRAND.emblem, capital: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["public", (form: React.ReactNode) => <PublicLayout>{form}</PublicLayout>, <LoginForm key="l" />],
    ["first-sign-in", (form: React.ReactNode) => <WelcomeLayout>{form}</WelcomeLayout>, <PasswordStepForm key="p" />],
  ])(
    "the %s frame has one main landmark, #main, holding the form and the foot line, with the panel outside it",
    (_name, frame, form) => {
      const { container } = renderWithClient(frame(form));
      const mains = screen.getAllByRole("main");
      expect(mains).toHaveLength(1);
      const main = mains[0]!;
      expect(main).toHaveAttribute("id", "main");
      expect(container.querySelectorAll("main")).toHaveLength(1);
      expect(main).toContainElement(container.querySelector("form"));
      expect(main).toContainElement(screen.getByText(T.auth.frame.foot));
      // the brand panel bleeds to the screen's edges like a banner, so it is not inside main (uicheck gutter rule)
      const region = panel();
      expect(main).not.toContainElement(region);
      expect(region.contains(main)).toBe(false);
      expect(main).not.toContainElement(emblem());
    },
  );

  it("the first-sign-in pages use the same panel with the emblem and the wider form side", () => {
    const { container } = renderWithClient(
      <WelcomeLayout>
        <PasswordStepForm />
      </WelcomeLayout>,
    );
    expect(emblem()).toBeInTheDocument();
    expect(within(panel()).getByText(T.portalLong)).toBeInTheDocument();
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
