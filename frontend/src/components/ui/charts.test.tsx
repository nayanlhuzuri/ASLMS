import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RateRing, SparkBars, StatusDot } from "./charts";

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
  vi.unstubAllGlobals();
});

const BUCKETS = [
  { answered: 4, failed: 0 },
  { answered: 2, failed: 2 },
  { answered: 0, failed: 0 },
];

describe("SparkBars", () => {
  it("carries its accessible name and stacks failed on answered", () => {
    stubMotion(false);
    const { container } = render(<SparkBars buckets={BUCKETS} label="Last 24 hours: 6 answered, 2 failed" />);
    expect(screen.getByRole("img", { name: "Last 24 hours: 6 answered, 2 failed" })).toBeInTheDocument();
    expect(screen.getAllByTestId("spark-bar")).toHaveLength(3);
    const rects = container.querySelectorAll("rect");
    // bar 1: answered at full height; bar 2: answered half, failed half on top; bar 3: an empty baseline mark
    expect(rects).toHaveLength(4);
    expect(container.querySelector("svg")).toHaveAttribute("data-motion", "on");
    expect(screen.getAllByTestId("spark-bar")[1]).toHaveStyle({ animationDelay: "10ms" });
  });

  it("under reduced motion the bars render at their final values with no animation", () => {
    stubMotion(true);
    const { container } = render(<SparkBars buckets={BUCKETS} label="bars" height={40} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("data-motion", "off");
    for (const bar of screen.getAllByTestId("spark-bar")) expect(bar.getAttribute("style")).toBeNull();
    const first = container.querySelector("rect")!;
    expect(first.getAttribute("height")).toBe("40");
  });
});

describe("RateRing", () => {
  it("carries its accessible name and sweeps to its value", () => {
    stubMotion(false);
    render(
      <RateRing value={0.75} label="75 % answered">
        <b>75 %</b>
      </RateRing>,
    );
    expect(screen.getByRole("img", { name: "75 % answered" })).toBeInTheDocument();
    const sweep = screen.getByTestId("ring-sweep");
    const c = Number(sweep.getAttribute("stroke-dasharray"));
    expect(Number(sweep.getAttribute("stroke-dashoffset"))).toBeCloseTo(c * 0.25, 1);
    expect(sweep.closest("svg")).toHaveAttribute("data-motion", "on");
  });

  it("under reduced motion the ring is drawn at its final value with no sweep", () => {
    stubMotion(true);
    render(<RateRing value={1} label="100 % answered" />);
    const sweep = screen.getByTestId("ring-sweep");
    expect(Number(sweep.getAttribute("stroke-dashoffset"))).toBe(0);
    expect(sweep.closest("svg")).toHaveAttribute("data-motion", "off");
    expect(sweep.getAttribute("class")).not.toMatch(/animate/);
  });

  it("draws no sweep without a value", () => {
    stubMotion(false);
    render(<RateRing value={null} label="No court calls in 24 h" />);
    expect(screen.queryByTestId("ring-sweep")).toBeNull();
    expect(screen.getByRole("img", { name: "No court calls in 24 h" })).toBeInTheDocument();
  });
});

describe("StatusDot", () => {
  it("pulses only with motion", () => {
    stubMotion(false);
    const { unmount } = render(<StatusDot tone="busy" pulse />);
    expect(screen.getByTestId("status-dot").className).toMatch(/pulse/);
    unmount();
    stubMotion(true);
    render(<StatusDot tone="busy" pulse />);
    expect(screen.getByTestId("status-dot").className).not.toMatch(/pulse/);
  });
});
