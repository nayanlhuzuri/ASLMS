/**
 * The Sign In links' move to the form (design home-page, decision 11): the click's default is prevented and no hash
 * is added, the step's first field takes the focus, no scroll when the card is in view, one instant `scrollIntoView`
 * under reduced motion, and an eased scroll that ends within `DURATION.med` plus one frame.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DURATION } from "@/components/ui/motion";

import { jumpToSignIn, listenForSignInLinks } from "./jumpToSignIn";

let stop: () => void = () => undefined;

/** The page: a Sign In link and the card with one step on show (and, on the code step, the password step leaving). */
function page(step: "password" | "code") {
  document.body.innerHTML = `
    <a href="#sign-in" id="link">Sign In</a>
    <div id="sign-in">
      ${step === "code" ? '<div data-step="password" inert><input name="email" type="email"></div>' : ""}
      <div data-step="${step}">
        ${step === "code" ? '<input name="code">' : '<input name="email" type="email"><input name="password" type="password">'}
      </div>
    </div>`;
}

/** Places the card at `top` (viewport coordinates), 400 px tall, in a 768 px window over a 4000 px page. */
function placeCard(top: number) {
  const card = document.getElementById("sign-in")!;
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ top, bottom: top + 400, left: 0, right: 400, width: 400, height: 400, x: 0, y: top, toJSON: () => ({}) });
  Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, value: 4000 });
  return card;
}

function motion(reduced: boolean) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("reduce") ? reduced : false, media: query })));
}

function click(): MouseEvent {
  const event = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
  document.getElementById("link")!.dispatchEvent(event);
  return event;
}

beforeEach(() => {
  window.location.hash = "";
  Element.prototype.scrollIntoView = vi.fn();
  stop = listenForSignInLinks();
});

afterEach(() => {
  stop();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("a click on a Sign In link", () => {
  it("prevents the default, leaves the hash empty and focuses the e-mail field", () => {
    motion(true);
    page("password");
    placeCard(1200);
    const event = click();
    expect(event.defaultPrevented).toBe(true);
    expect(window.location.hash).toBe("");
    expect(document.activeElement).toBe(document.querySelector("input[name=email]"));
  });

  it("on the code step focuses the code field, not the leaving step's field", () => {
    motion(true);
    page("code");
    placeCard(1200);
    click();
    expect(document.activeElement).toBe(document.querySelector("input[name=code]"));
  });

  it("with the card wholly in view, makes no scroll call and only moves the focus", () => {
    motion(false);
    page("password");
    placeCard(100);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    const raf = vi.spyOn(window, "requestAnimationFrame");
    click();
    expect(scrollTo).not.toHaveBeenCalled();
    expect(raf).not.toHaveBeenCalled();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.querySelector("input[name=email]"));
  });

  it("under reduced motion calls scrollIntoView once, with no smooth behaviour", () => {
    motion(true);
    page("password");
    placeCard(1200);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    click();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(scrollTo).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.querySelector("input[name=email]"));
  });

  it("with motion, the scroll ends at the card less --s4 within DURATION.med plus one frame, then focuses", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance", "setTimeout", "Date"] });
    motion(false);
    page("password");
    placeCard(1200);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    const focus = vi.spyOn(HTMLInputElement.prototype, "focus");
    click();
    expect(scrollTo).not.toHaveBeenCalled();
    vi.advanceTimersByTime(DURATION.med / 2);
    expect(scrollTo).toHaveBeenCalled();
    expect(focus).not.toHaveBeenCalled();
    vi.advanceTimersByTime(DURATION.med / 2 + 16);
    const last = scrollTo.mock.calls.at(-1)! as unknown as [number, number];
    expect(last).toEqual([0, 1200 - 16]);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    const calls = scrollTo.mock.calls.length;
    vi.advanceTimersByTime(200);
    expect(scrollTo.mock.calls.length).toBe(calls);
  });

  it("does nothing for a modified click or a click elsewhere, and nothing without the card", () => {
    motion(true);
    page("password");
    placeCard(1200);
    const modified = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ctrlKey: true });
    document.getElementById("link")!.dispatchEvent(modified);
    expect(modified.defaultPrevented).toBe(false);
    document.body.innerHTML = "";
    expect(jumpToSignIn(true)).toBeNull();
  });
});
