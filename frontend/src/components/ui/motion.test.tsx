import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "@/test/render";

import { ConfirmDialog, Dialog, Kpi, Modal, SidePanel } from "./index";
import { useCountUp, usePrefersReducedMotion, usePresence, useSlidingMark } from "./motion";

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

afterEach(() => {
  vi.useRealTimers();
});

describe("reduced motion (design portal-ui-redesign, decision 13)", () => {
  it("reads the media query", () => {
    stubMotion(true);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(true);
    stubMotion(false);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(false);
  });

  it("useCountUp returns the final value at once", () => {
    stubMotion(true);
    const { result, rerender } = renderHook(({ n }) => useCountUp(n), { initialProps: { n: 42 } });
    expect(result.current).toBe(42);
    rerender({ n: 128400 });
    expect(result.current).toBe(128400);
  });

  it("usePresence unmounts with no delay", () => {
    stubMotion(true);
    const { result, rerender } = renderHook(({ open }) => usePresence(open, 220), { initialProps: { open: true } });
    expect(result.current.mounted).toBe(true);
    rerender({ open: false });
    expect(result.current).toEqual({ mounted: false, closing: false });
  });

  it("a Kpi shows its final number immediately", () => {
    stubMotion(true);
    renderWithClient(<Kpi label="Files with me" value={128400} />);
    expect(screen.getByText("1,28,400")).toBeInTheDocument();
  });

  it("a dialog closes with no exit delay left", async () => {
    stubMotion(true);
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <Dialog open={open} title="New User" onClose={() => setOpen(false)}>
          <p>body</p>
        </Dialog>
      );
    }
    renderWithClient(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("with motion", () => {
  it("usePresence keeps the element for the exit duration", () => {
    vi.useFakeTimers();
    stubMotion(false);
    const { result, rerender } = renderHook(({ open }) => usePresence(open, 220), { initialProps: { open: true } });
    rerender({ open: false });
    expect(result.current).toEqual({ mounted: true, closing: true });
    act(() => {
      vi.advanceTimersByTime(219);
    });
    expect(result.current.mounted).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toEqual({ mounted: false, closing: false });
    rerender({ open: true });
    expect(result.current).toEqual({ mounted: true, closing: false });
  });

  it("useCountUp counts up over the frames to the final value", () => {
    stubMotion(false);
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const { result } = renderHook(() => useCountUp(120, 12));
    expect(result.current).toBe(0);
    act(() => frames.shift()!(0));
    expect(result.current).toBe(10);
    for (let i = 0; i < 11; i += 1) act(() => frames.shift()!(0));
    expect(result.current).toBe(120);
    expect(frames).toHaveLength(0);
  });

  it("a dialog stays for its exit animation, then unmounts", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubMotion(false);
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <Dialog open={open} title="New User" onClose={() => setOpen(false)}>
          <p>body</p>
        </Dialog>
      );
    }
    renderWithClient(<Harness />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(220);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("a closing overlay is inert (review of round 1, fixed in round 2)", () => {
  it("a confirm dialog easing out drops a second submit, so an append-only write is sent once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubMotion(false);
    const confirm = vi.fn();
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <ConfirmDialog
          open={open}
          title="Add Note"
          onClose={() => setOpen(false)}
          onConfirm={() => {
            confirm();
            setOpen(false);
          }}
        >
          <p>body</p>
        </ConfirmDialog>
      );
    }
    renderWithClient(<Harness />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const submit = screen.getByRole("button", { name: "Confirm" });
    // the footer button submits its form through the `form` attribute (the Action dialog template, round 3)
    const form = (submit as HTMLButtonElement).form!;
    await user.click(submit);
    expect(confirm).toHaveBeenCalledTimes(1);
    // still on screen for the exit animation, but inert and without pointer events
    const overlay = document.querySelector("[data-closing='true']")!;
    expect(overlay).not.toBeNull();
    expect(overlay).toHaveAttribute("inert");
    fireEvent.submit(form);
    expect(confirm).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(220);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["modal", "panel"] as const)("a %s easing out is inert and its overlay click does nothing", async (kind) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubMotion(false);
    const closed = vi.fn();
    function Harness() {
      const [open, setOpen] = useState(true);
      const close = () => {
        closed();
        setOpen(false);
      };
      return kind === "modal" ? (
        <Modal open={open} title="Case" onClose={close}>
          <p>body</p>
        </Modal>
      ) : (
        <SidePanel open={open} title="File" onClose={close}>
          <p>body</p>
        </SidePanel>
      );
    }
    renderWithClient(<Harness />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.keyboard("{Escape}");
    expect(closed).toHaveBeenCalledTimes(1);
    const overlay = document.querySelector("[data-closing='true']") as HTMLElement;
    expect(overlay).toHaveAttribute("inert");
    fireEvent.click(overlay);
    expect(closed).toHaveBeenCalledTimes(1);
  });
});

describe("useSlidingMark (design portal-motion, decision 10)", () => {
  function Row({ current }: { current: string }) {
    const ref = useRef<HTMLDivElement>(null);
    const box = useSlidingMark(ref, "[data-on='true']", [current]);
    return (
      <div ref={ref} data-testid="row">
        {["a", "b"].map((k) => (
          <span key={k} data-key={k} data-on={k === current ? "true" : undefined}>
            {k}
          </span>
        ))}
        {box ? <i aria-hidden="true" data-testid="mark" style={{ left: box.left, width: box.width }} /> : null}
      </div>
    );
  }

  it("returns the selected item's box and follows a resize", () => {
    const sizes: Record<string, { left: number; width: number }> = { a: { left: 0, width: 40 }, b: { left: 50, width: 70 } };
    const left = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
      return sizes[this.dataset.key ?? ""]?.left ?? 0;
    });
    const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) {
      return sizes[this.dataset.key ?? ""]?.width ?? 0;
    });
    const observers: { cb: ResizeObserverCallback; els: Element[] }[] = [];
    class FakeResizeObserver {
      els: Element[] = [];
      constructor(cb: ResizeObserverCallback) {
        observers.push({ cb, els: this.els });
      }
      observe(el: Element) {
        this.els.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    try {
      const { rerender } = render(<Row current="a" />);
      expect(screen.getByTestId("mark")).toHaveStyle({ left: "0px", width: "40px" });
      rerender(<Row current="b" />);
      expect(screen.getByTestId("mark")).toHaveStyle({ left: "50px", width: "70px" });
      const watcher = observers[observers.length - 1]!;
      expect(watcher.els).toContain(screen.getByTestId("row"));
      expect(watcher.els).not.toContain(screen.getByTestId("mark"));
      sizes.b = { left: 50, width: 90 };
      act(() => watcher.cb([], watcher as unknown as ResizeObserver));
      expect(screen.getByTestId("mark")).toHaveStyle({ width: "90px" });
    } finally {
      left.mockRestore();
      width.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("returns null while nothing matches", () => {
    render(<Row current="z" />);
    expect(screen.queryByTestId("mark")).toBeNull();
  });
});
