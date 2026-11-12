import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { notifyOverlayOpen, onOverlayOpen } from "./overlayEvents";
import { useOverlay } from "./overlays";

/* design control-spacing-sweep, decision 17: the listener set behind "an overlay has opened" */

describe("overlayEvents", () => {
  it("runs each listener once per notifyOverlayOpen(), and not after its unsubscribe", () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = onOverlayOpen(a);
    const offB = onOverlayOpen(b);
    notifyOverlayOpen();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    offA();
    notifyOverlayOpen();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
    offB();
    notifyOverlayOpen();
    expect(b).toHaveBeenCalledTimes(2);
  });

  it("useOverlay notifies once each time it becomes active, never on closing, and only after the focus moved in", () => {
    const root = document.createElement("div");
    const field = document.createElement("input");
    root.appendChild(field);
    document.body.appendChild(root);
    const focusAtCall: (Element | null)[] = [];
    const off = onOverlayOpen(() => focusAtCall.push(document.activeElement));
    try {
      const ref = { current: root };
      const { rerender, unmount } = renderHook(({ active }) => useOverlay(ref, active, () => {}), { initialProps: { active: false } });
      expect(focusAtCall).toHaveLength(0);
      act(() => rerender({ active: true }));
      expect(focusAtCall).toEqual([field]);
      act(() => rerender({ active: true }));
      expect(focusAtCall).toHaveLength(1);
      act(() => rerender({ active: false }));
      expect(focusAtCall).toHaveLength(1);
      act(() => rerender({ active: true }));
      expect(focusAtCall).toHaveLength(2);
      unmount();
      expect(focusAtCall).toHaveLength(2);
    } finally {
      off();
      root.remove();
    }
  });
});
