import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setFlash } from "@/lib/flash";
import { nav, resetNav } from "@/test/nav";
import { renderWithClient, toastStatus } from "@/test/render";

import { Dialog, DURATION, Modal, SidePanel, TOAST_MS, ToastProvider, useToast, type ToastLink } from "./index";

/*
 * The confirmation toast (design portal-motion, decisions 1 to 8; Tests 1).
 */

/** Answers the reduced-motion media query as given. */
function stubMotion(reduced: boolean) {
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

/** The toast function of the rendered Raiser, kept after each render. */
const raiser: { current: (text: string, link?: ToastLink) => void } = { current: () => {} };

function Raiser() {
  const toast = useToast();
  useEffect(() => {
    raiser.current = toast;
  });
  return (
    <>
      <input aria-label="Typing Here" />
      <button type="button">Elsewhere</button>
    </>
  );
}

function card(): HTMLElement {
  return document.querySelector<HTMLElement>("[data-ui='toast']")!;
}

function show(text: string, link?: ToastLink) {
  act(() => raiser.current(text, link));
}

beforeEach(() => {
  resetNav("/");
  sessionStorage.clear();
  stubMotion(true);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the toast's structure (decision 5)", () => {
  it("has a visually hidden polite status region before any toast, and the card is a group named by the text", () => {
    renderWithClient(<Raiser />);
    const status = toastStatus();
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-atomic", "true");
    expect(status).toHaveClass("visually-hidden");
    expect(status).toHaveTextContent("");
    show("Saved.");
    expect(status).toHaveTextContent("Saved.");
    const group = screen.getByRole("group", { name: "Saved." });
    expect(group).toBe(card());
    const text = within(group).getByText("Saved.");
    expect(text).toHaveAttribute("aria-hidden", "true");
    expect(within(group).getByRole("button", { name: "Close Message" })).toBeInTheDocument();
  });

  it("the host is the provider's last element and carries the motion-layer mark", () => {
    const { container } = render(
      <ToastProvider>
        <p>Page</p>
      </ToastProvider>,
    );
    const host = container.lastElementChild as HTMLElement;
    expect(host).toHaveAttribute("data-ui", "toast-host");
    expect(host).toHaveAttribute("data-motion-layer");
    expect(container.firstElementChild).toHaveTextContent("Page");
  });
});

describe("the timer (decision 4)", () => {
  it("a text-only toast is still shown at 5999 ms and gone at 6000 ms", () => {
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("Saved.");
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => vi.advanceTimersByTime(1));
    expect(toastStatus()).toHaveTextContent("");
    expect(card()).not.toHaveAttribute("data-open");
    expect(card()).toBeEmptyDOMElement();
  });

  it("pauses while the pointer is over the card, and leaving starts the full time again", () => {
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("Saved.");
    act(() => vi.advanceTimersByTime(4000));
    fireEvent.mouseEnter(card());
    act(() => vi.advanceTimersByTime(20000));
    expect(toastStatus()).toHaveTextContent("Saved.");
    fireEvent.mouseLeave(card());
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => vi.advanceTimersByTime(1));
    expect(toastStatus()).toHaveTextContent("");
  });

  it("pauses while focus is inside the card, and starts again when focus moves out", () => {
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("Saved.");
    const close = within(card()).getByRole("button", { name: "Close Message" });
    act(() => close.focus());
    act(() => vi.advanceTimersByTime(30000));
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => screen.getByRole("button", { name: "Elsewhere" }).focus());
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => vi.advanceTimersByTime(1));
    expect(toastStatus()).toHaveTextContent("");
  });

  it("a toast with a link shows the link and is still shown after 60 s", () => {
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("Claimed for Education.", { href: "/cases/X", label: "Open Case Page" });
    expect(within(card()).getByRole("link", { name: "Open Case Page" })).toHaveAttribute("href", "/cases/X");
    expect(toastStatus()).toHaveTextContent("Claimed for Education. Open Case Page");
    act(() => vi.advanceTimersByTime(60000));
    expect(within(card()).getByRole("link", { name: "Open Case Page" })).toBeInTheDocument();
  });
});

describe("closing and replacing (decision 4)", () => {
  it("Close Message closes it", () => {
    renderWithClient(<Raiser />);
    show("Saved.");
    fireEvent.click(within(card()).getByRole("button", { name: "Close Message" }));
    expect(toastStatus()).toHaveTextContent("");
    expect(card()).toBeEmptyDOMElement();
  });

  it("Escape with focus inside closes it and gives focus back where it came from", () => {
    renderWithClient(<Raiser />);
    const typing = screen.getByRole("textbox", { name: "Typing Here" });
    act(() => typing.focus());
    show("Saved.");
    const close = within(card()).getByRole("button", { name: "Close Message" });
    act(() => close.focus());
    fireEvent.keyDown(close, { key: "Escape" });
    expect(toastStatus()).toHaveTextContent("");
    expect(typing).toHaveFocus();
  });

  it("Escape outside the toast leaves it alone", () => {
    renderWithClient(<Raiser />);
    show("Saved.");
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Typing Here" }), { key: "Escape" });
    expect(toastStatus()).toHaveTextContent("Saved.");
  });

  it("a second toast replaces the text in the same card and restarts the timer; never more than one card", () => {
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("First.");
    const first = card();
    act(() => vi.advanceTimersByTime(5000));
    show("Second.");
    expect(document.querySelectorAll("[data-ui='toast']")).toHaveLength(1);
    expect(card()).toBe(first);
    expect(toastStatus()).toHaveTextContent("Second.");
    expect(screen.queryByRole("group", { name: "First." })).toBeNull();
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(toastStatus()).toHaveTextContent("Second.");
    act(() => vi.advanceTimersByTime(1));
    expect(toastStatus()).toHaveTextContent("");
  });

  it("never takes focus", () => {
    renderWithClient(<Raiser />);
    const typing = screen.getByRole("textbox", { name: "Typing Here" });
    act(() => typing.focus());
    show("Saved.");
    show("Saved again.", { href: "/x", label: "Open" });
    expect(document.activeElement).toBe(typing);
  });
});

describe("navigation and the flash (decisions 3 and 4)", () => {
  it("a change of pathname closes the toast; a change of the query string does not", () => {
    const view = renderWithClient(<Raiser />);
    show("Saved.", { href: "/x", label: "Open" });
    nav.search = new URLSearchParams("view=department");
    view.rerender(<Raiser />);
    expect(toastStatus()).toHaveTextContent("Saved.");
    nav.pathname = "/inbox";
    view.rerender(<Raiser />);
    expect(toastStatus()).toHaveTextContent("");
  });

  it("shows a flash on mount, then clears it", () => {
    setFlash("Case sent away.");
    renderWithClient(<Raiser />);
    expect(toastStatus()).toHaveTextContent("Case sent away.");
    expect(sessionStorage.getItem("aslms.flash")).toBeNull();
  });

  it("shows a flash brought by a change of pathname, which that change does not close", () => {
    const view = renderWithClient(<Raiser />);
    show("Older.");
    setFlash("Case sent away.");
    nav.pathname = "/inbox";
    view.rerender(<Raiser />);
    expect(toastStatus()).toHaveTextContent("Case sent away.");
    expect(sessionStorage.getItem("aslms.flash")).toBeNull();
  });
});

describe("motion (decision 8)", () => {
  it("under reduced motion the card is empty at once after Close, with no data-closing", () => {
    stubMotion(true);
    renderWithClient(<Raiser />);
    show("Saved.");
    expect(card()).toHaveAttribute("data-open");
    fireEvent.click(within(card()).getByRole("button", { name: "Close Message" }));
    expect(card()).not.toHaveAttribute("data-closing");
    expect(card()).toBeEmptyDOMElement();
  });

  it("with motion the card keeps its text with data-closing for DURATION.med, then empties", () => {
    stubMotion(false);
    vi.useFakeTimers();
    renderWithClient(<Raiser />);
    show("Saved.");
    fireEvent.click(within(card()).getByRole("button", { name: "Close Message" }));
    expect(card()).toHaveAttribute("data-closing");
    expect(card()).not.toHaveAttribute("data-open");
    expect(within(card()).getByText("Saved.")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(DURATION.med - 1));
    expect(card()).toHaveAttribute("data-closing");
    act(() => vi.advanceTimersByTime(1));
    expect(card()).not.toHaveAttribute("data-closing");
    expect(card()).toBeEmptyDOMElement();
  });
});

describe("outside a provider (decision 1)", () => {
  it("useToast() throws an error naming ToastProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      expect(() => render(<Raiser />)).toThrow(/ToastProvider/);
    } finally {
      spy.mockRestore();
    }
  });
});

/** A page that opens one kit overlay at a time from its buttons, and raises toasts by `show`. */
type Which = "modal" | "dialog" | "panel" | null;
const opener: { current: (w: Which) => void } = { current: () => {} };

function OverlayPage() {
  const [which, setWhich] = useState<Which>(null);
  useEffect(() => {
    opener.current = setWhich;
  }, []);
  const close = () => setWhich(null);
  return (
    <>
      <Raiser />
      <Modal open={which === "modal"} title="Case Details" onClose={close}>
        <button type="button">Modal Action</button>
      </Modal>
      <Dialog open={which === "dialog"} title="Add Note" onClose={close}>
        <input aria-label="Note Text" />
      </Dialog>
      <SidePanel open={which === "panel"} title="Remarks" onClose={close}>
        <button type="button">Panel Action</button>
      </SidePanel>
    </>
  );
}

function openOverlay(w: Which) {
  act(() => opener.current(w));
}

describe("an overlay opening closes the toast (design control-spacing-sweep, decision 17)", () => {
  it("a link toast closes at once under reduced motion when a Modal opens", () => {
    renderWithClient(<OverlayPage />);
    show("Claimed for Education.", { href: "/cases/X", label: "Open Case Page" });
    expect(within(card()).getByRole("link", { name: "Open Case Page" })).toBeInTheDocument();
    openOverlay("modal");
    expect(screen.getByRole("dialog", { name: "Case Details" })).toBeInTheDocument();
    expect(card()).toBeEmptyDOMElement();
    expect(toastStatus()).toHaveTextContent("");
  });

  it("with motion, a text-only toast leaves over DURATION.med when a Dialog opens", () => {
    stubMotion(false);
    vi.useFakeTimers();
    renderWithClient(<OverlayPage />);
    show("Saved.");
    openOverlay("dialog");
    expect(card()).toHaveAttribute("data-closing");
    expect(card()).not.toHaveAttribute("data-open");
    act(() => vi.advanceTimersByTime(DURATION.med));
    expect(card()).toBeEmptyDOMElement();
    expect(toastStatus()).toHaveTextContent("");
  });

  it("a text-only toast closes when a SidePanel opens", () => {
    renderWithClient(<OverlayPage />);
    show("Saved.");
    openOverlay("panel");
    expect(card()).toBeEmptyDOMElement();
    expect(toastStatus()).toHaveTextContent("");
  });

  it("a toast raised while a Dialog is already open stays, and closes after TOAST_MS", () => {
    vi.useFakeTimers();
    renderWithClient(<OverlayPage />);
    openOverlay("dialog");
    show("Saved.");
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(toastStatus()).toHaveTextContent("Saved.");
    act(() => vi.advanceTimersByTime(1));
    expect(toastStatus()).toHaveTextContent("");
  });

  it("closing an overlay does not close the toast", () => {
    vi.useFakeTimers();
    renderWithClient(<OverlayPage />);
    openOverlay("modal");
    show("Claimed for Education.", { href: "/cases/X", label: "Open Case Page" });
    openOverlay(null);
    act(() => vi.advanceTimersByTime(60000));
    expect(within(card()).getByRole("link", { name: "Open Case Page" })).toBeInTheDocument();
  });

  it("the focus goes to the dialog's first control, not back behind it, even from inside the toast", () => {
    renderWithClient(<OverlayPage />);
    show("Saved.");
    act(() => within(card()).getByRole("button", { name: "Close Message" }).focus());
    openOverlay("dialog");
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Note Text" }));
    expect(card()).toBeEmptyDOMElement();
  });
});

describe("every toast is announced, even a repeat (design control-spacing-sweep, decision 18)", () => {
  it("the same words twice keep the region and replace its inner node; other words replace it too", () => {
    renderWithClient(<Raiser />);
    const status = toastStatus();
    show("Saved.");
    const first = status.firstElementChild;
    expect(first).not.toBeNull();
    show("Saved.");
    expect(toastStatus()).toBe(status);
    expect(status).toHaveTextContent("Saved.");
    const second = status.firstElementChild;
    expect(second).not.toBe(first);
    show("Removed.");
    expect(status).toHaveTextContent("Removed.");
    expect(status.firstElementChild).not.toBe(second);
  });

  it("the region is the same node before, during and after a toast", () => {
    renderWithClient(<Raiser />);
    const before = toastStatus();
    show("Saved.");
    expect(toastStatus()).toBe(before);
    fireEvent.click(within(card()).getByRole("button", { name: "Close Message" }));
    expect(toastStatus()).toBe(before);
    expect(before).toHaveTextContent("");
  });
});
