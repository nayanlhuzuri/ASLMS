import { act, fireEvent, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "@/test/render";

import { ConfirmDialog, Dialog, Kpi, Modal, SidePanel } from "./index";
import { useCountUp, usePrefersReducedMotion, usePresence } from "./motion";

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
        <Dialog open={open} title="New user" onClose={() => setOpen(false)}>
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
        <Dialog open={open} title="New user" onClose={() => setOpen(false)}>
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
          title="Add note"
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
