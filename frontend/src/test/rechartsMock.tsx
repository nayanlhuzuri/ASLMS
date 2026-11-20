/**
 * A stand-in for `recharts` in component tests (design state-insights, round 2 "Tests"): jsdom measures nothing, so the
 * real charts would draw no SVG. Each component renders a plain element carrying its children and records its props,
 * so a test can read what the kit asked Recharts to draw (a `stackId`, `isAnimationActive`, a `Cell`'s fill).
 * Use: `vi.mock("recharts", async () => (await import("@/test/rechartsMock")).rechartsModule);`
 */
import type { ReactNode } from "react";

export interface RechartsCall {
  name: string;
  props: Record<string, unknown>;
}

export const rechartsCalls: RechartsCall[] = [];

export function resetRecharts(): void {
  rechartsCalls.length = 0;
}

export function callsOf(name: string): Record<string, unknown>[] {
  return rechartsCalls.filter((c) => c.name === name).map((c) => c.props);
}

function make(name: string) {
  function Stand(props: Record<string, unknown> & { children?: ReactNode }) {
    rechartsCalls.push({ name, props });
    return <div data-recharts={name}>{props.children}</div>;
  }
  Stand.displayName = `Recharts${name}`;
  return Stand;
}

export const rechartsModule = {
  ResponsiveContainer: make("ResponsiveContainer"),
  BarChart: make("BarChart"),
  LineChart: make("LineChart"),
  Bar: make("Bar"),
  Line: make("Line"),
  Cell: make("Cell"),
  XAxis: make("XAxis"),
  YAxis: make("YAxis"),
  CartesianGrid: make("CartesianGrid"),
  Tooltip: make("Tooltip"),
  Legend: make("Legend"),
};
