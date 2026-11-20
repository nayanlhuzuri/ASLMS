"use client";

/**
 * The Insights chart kit (design state-insights, decision 31): Recharts, pinned exactly, wrapped once here so the
 * screens never touch the library. Loaded only by `/insights`, through `next/dynamic` with `ssr: false`, and kept out of
 * the kit's index on purpose: importing `@/components/ui` must never pull Recharts into another route.
 *
 * - `ChartCard`: the title, the coverage line, "View as Table" (the same numbers in a `DataTable` whose rows carry the
 *   filter buttons, so every click has a keyboard path) and the empty state.
 * - `HBarChart`: clickable horizontal bars; the selected bar is marked by colour **and** a tick in its label.
 * - `StackedBarChart`: kind of case × age band, stacked.
 * - `GroupedBarChart`: the three department bands side by side, never stacked and never added together.
 * - `TrendChart`: two lines with points.
 *
 * Colours come from the CSS custom properties (`--chart-1` … `--chart-8`, `--chart-selected` and the row 190 hearing
 * tones), read once at run time by `useChartTokens()`; no colour literal is written here. Every chart is a `role="img"`
 * with a summary as its accessible name, keeps Recharts' `accessibilityLayer`, and animates only without reduced motion.
 */
import { useId, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatNumber } from "@/lib/format";
import { chartSummary, shortLabel, tickLabel } from "@/lib/insights";
import { T } from "@/lib/messages";

import { Button } from "./controls";
import { EmptyState } from "./feedback";
import { Card } from "./layout";
import { usePrefersReducedMotion } from "./motion";
import s from "./insightCharts.module.css";

/** The token names the charts read (decision 31): the series, the selected bar, the grid, the axis, the hearing tones. */
export const CHART_TOKEN_NAMES = {
  series: ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6", "--chart-7", "--chart-8"],
  selected: "--chart-selected",
  grid: "--chart-grid",
  axis: "--chart-axis",
  surface: "--surface",
  strong: "--red",
  soft: "--ochre",
  plain: "--action",
  warning: "--text-2",
  muted: "--text-3",
} as const;

export interface ChartTokens {
  series: string[];
  selected: string;
  grid: string;
  axis: string;
  surface: string;
  strong: string;
  soft: string;
  plain: string;
  warning: string;
  muted: string;
}

/** A token's value from the document, else `currentColor` (a browser that cannot read it still draws the bars). */
export function readToken(name: string, root: Element | null = typeof document === "undefined" ? null : document.documentElement): string {
  if (!root || typeof getComputedStyle !== "function") return "currentColor";
  const value = getComputedStyle(root).getPropertyValue(name).trim();
  return value || "currentColor";
}

export function readChartTokens(root?: Element | null): ChartTokens {
  const n = CHART_TOKEN_NAMES;
  return {
    series: n.series.map((t) => readToken(t, root)),
    selected: readToken(n.selected, root),
    grid: readToken(n.grid, root),
    axis: readToken(n.axis, root),
    surface: readToken(n.surface, root),
    strong: readToken(n.strong, root),
    soft: readToken(n.soft, root),
    plain: readToken(n.plain, root),
    warning: readToken(n.warning, root),
    muted: readToken(n.muted, root),
  };
}

/** The chart colours, read once when the chart kit first draws (decision 31). */
export function useChartTokens(): ChartTokens {
  const [tokens] = useState(() => readChartTokens());
  return tokens;
}

export interface BarDatum {
  key: string;
  label: string;
  count: number;
}

const AXIS_FONT = 12;
const ROW_H = 30;

/** A card around one chart: title, coverage line, View as Table, the empty state (decision 31). */
export function ChartCard({
  title,
  coverage,
  table,
  empty = false,
  emptyText = T.insights.charts.empty,
  actions,
  children,
}: {
  title: string;
  coverage?: string | null;
  /** The same numbers as a table whose rows carry the filter buttons. */
  table: ReactNode;
  empty?: boolean;
  emptyText?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <Card
      title={title}
      wrapHead
      actions={
        <>
          {actions}
          {empty ? null : (
            <Button variant="ghost" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
              {asTable ? T.insights.charts.viewChart : T.insights.charts.viewTable}
            </Button>
          )}
        </>
      }
    >
      <div className={s.body}>
        {coverage ? <p className={s.coverage}>{coverage}</p> : null}
        {empty ? <EmptyState compact>{emptyText}</EmptyState> : asTable ? table : children}
      </div>
    </Card>
  );
}

/** The width of the category axis: about the longest short label, within a third of a phone's width. */
function axisWidth(labels: string[]): number {
  const longest = Math.max(4, ...labels.map((l) => l.length));
  return Math.min(190, Math.max(72, Math.round(longest * AXIS_FONT * 0.56) + 12));
}

function useMotion(): boolean {
  return !usePrefersReducedMotion();
}

/** Clickable horizontal bars; `colourOf` gives a bar its own colour (the hearing bands), else the first series. */
export function HBarChart({
  title,
  data,
  selected,
  onSelect,
  colourOf,
}: {
  /** The chart's name in its accessible summary. */
  title: string;
  data: readonly BarDatum[];
  selected?: string | null;
  onSelect?: (key: string) => void;
  colourOf?: (key: string, tokens: ChartTokens) => string;
}) {
  const tokens = useChartTokens();
  const animate = useMotion();
  const rows = data.map((d) => ({ ...d, axis: tickLabel(shortLabel(d.label), d.key === selected) }));
  const height = Math.max(96, rows.length * ROW_H + 32);
  return (
    <div
      className={s.chart}
      role="img"
      aria-label={chartSummary(title, data, (n) => formatNumber(n))}
      data-motion={animate ? "on" : "off"}
      data-selected={selected ?? undefined}
    >
      <ResponsiveContainer width="100%" height={height} initialDimension={{ width: 320, height }}>
        <BarChart data={rows} layout="vertical" accessibilityLayer margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid horizontal={false} stroke={tokens.grid} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: tokens.axis, fontSize: AXIS_FONT }} stroke={tokens.grid} />
          <YAxis
            type="category"
            dataKey="axis"
            width={axisWidth(rows.map((r) => r.axis))}
            interval={0}
            tick={{ fill: tokens.axis, fontSize: AXIS_FONT }}
            stroke={tokens.grid}
          />
          <Tooltip formatter={(v) => formatNumber(Number(v))} labelFormatter={(_l, p) => fullLabel(p)} />
          <Bar
            dataKey="count"
            name={T.insights.charts.cases}
            isAnimationActive={animate}
            cursor={onSelect ? "pointer" : undefined}
            onClick={onSelect ? (item) => onSelect(String((item.payload as BarDatum).key)) : undefined}
          >
            {rows.map((r) => (
              <Cell
                key={r.key}
                fill={r.key === selected ? tokens.selected : colourOf ? colourOf(r.key, tokens) : tokens.series[0]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function fullLabel(payload: readonly { payload?: unknown }[] | undefined): string {
  const row = payload?.[0]?.payload as { label?: string } | undefined;
  return row?.label ?? "";
}

export interface SeriesDef {
  key: string;
  label: string;
}

export interface MultiRow {
  key: string;
  label: string;
  values: Record<string, number>;
}

/** Kind of case × age band, stacked (decision 22); a click on a row sets its kind. */
export function StackedBarChart({
  title,
  rows,
  series,
  selected,
  onSelect,
}: {
  title: string;
  rows: readonly MultiRow[];
  series: readonly SeriesDef[];
  selected?: string | null;
  onSelect?: (rowKey: string) => void;
}) {
  const tokens = useChartTokens();
  const animate = useMotion();
  const data = rows.map((r) => ({ key: r.key, label: r.label, axis: tickLabel(shortLabel(r.label), r.key === selected), ...r.values }));
  const height = Math.max(120, data.length * ROW_H + 72);
  const totals = rows.map((r) => ({ label: r.label, count: Object.values(r.values).reduce((a, b) => a + b, 0) }));
  return (
    <div className={s.chart} role="img" aria-label={chartSummary(title, totals, (n) => formatNumber(n))} data-motion={animate ? "on" : "off"}>
      <ResponsiveContainer width="100%" height={height} initialDimension={{ width: 320, height }}>
        <BarChart data={data} layout="vertical" accessibilityLayer margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid horizontal={false} stroke={tokens.grid} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: tokens.axis, fontSize: AXIS_FONT }} stroke={tokens.grid} />
          <YAxis
            type="category"
            dataKey="axis"
            width={axisWidth(data.map((d) => d.axis))}
            interval={0}
            tick={{ fill: tokens.axis, fontSize: AXIS_FONT }}
            stroke={tokens.grid}
          />
          <Tooltip formatter={(v) => formatNumber(Number(v))} labelFormatter={(_l, p) => fullLabel(p)} />
          <Legend wrapperStyle={{ fontSize: AXIS_FONT }} />
          {series.map((sd, i) => (
            <Bar
              key={sd.key}
              dataKey={sd.key}
              name={sd.label}
              stackId="stack"
              fill={tokens.series[i % tokens.series.length]}
              isAnimationActive={animate}
              cursor={onSelect ? "pointer" : undefined}
              onClick={onSelect ? (item) => onSelect(String((item.payload as { key: string }).key)) : undefined}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * The three department bands side by side (decision 21): one bar per band, never stacked (no `stackId`), and no total
 * anywhere. A click on a band's bar sets that department and band.
 */
export function GroupedBarChart({
  title,
  rows,
  series,
  selected,
  onSelect,
}: {
  title: string;
  rows: readonly MultiRow[];
  series: readonly SeriesDef[];
  selected?: { row: string; series: string | null } | null;
  onSelect?: (rowKey: string, seriesKey: string) => void;
}) {
  const tokens = useChartTokens();
  const animate = useMotion();
  const data = rows.map((r) => ({ key: r.key, label: r.label, axis: tickLabel(shortLabel(r.label), r.key === selected?.row), ...r.values }));
  const height = Math.max(140, data.length * series.length * 14 + data.length * 12 + 72);
  const parts = rows.map((r) => ({ label: `${r.label} (${series.map((sd) => `${sd.label} ${formatNumber(r.values[sd.key] ?? 0)}`).join("; ")})`, count: Math.max(0, ...Object.values(r.values)) }));
  const summary = `${title}: ${parts.map((p) => p.label).slice(0, 8).join(", ")}${parts.length > 8 ? `, and ${parts.length - 8} more` : ""}`;
  return (
    <div className={s.chart} role="img" aria-label={rows.length ? summary : `${title}: no cases`} data-motion={animate ? "on" : "off"} data-grouped="">
      <ResponsiveContainer width="100%" height={height} initialDimension={{ width: 320, height }}>
        <BarChart data={data} layout="vertical" accessibilityLayer barGap={1} margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid horizontal={false} stroke={tokens.grid} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: tokens.axis, fontSize: AXIS_FONT }} stroke={tokens.grid} />
          <YAxis
            type="category"
            dataKey="axis"
            width={axisWidth(data.map((d) => d.axis))}
            interval={0}
            tick={{ fill: tokens.axis, fontSize: AXIS_FONT }}
            stroke={tokens.grid}
          />
          <Tooltip formatter={(v) => formatNumber(Number(v))} labelFormatter={(_l, p) => fullLabel(p)} />
          <Legend wrapperStyle={{ fontSize: AXIS_FONT }} />
          {series.map((sd, i) => (
            <Bar
              key={sd.key}
              dataKey={sd.key}
              name={sd.label}
              isAnimationActive={animate}
              cursor={onSelect ? "pointer" : undefined}
              onClick={onSelect ? (item) => onSelect(String((item.payload as { key: string }).key), sd.key) : undefined}
            >
              {data.map((d) => (
                <Cell
                  key={d.key}
                  fill={
                    selected && selected.row === d.key && (selected.series === null || selected.series === sd.key)
                      ? tokens.selected
                      : tokens.series[i % tokens.series.length]
                  }
                />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface TrendDatum {
  key: string;
  label: string;
  a: number;
  b: number;
}

/** Two lines with points (registrations against disposals); a click on a month calls `onSelect(month)`. */
export function TrendChart({
  title,
  data,
  aLabel,
  bLabel,
  onSelect,
}: {
  title: string;
  data: readonly TrendDatum[];
  aLabel: string;
  bLabel: string;
  onSelect?: (key: string) => void;
}) {
  const tokens = useChartTokens();
  const animate = useMotion();
  const id = useId();
  const summary = `${title}: ${data.map((d) => `${d.label} ${aLabel} ${formatNumber(d.a)}, ${bLabel} ${formatNumber(d.b)}`).join("; ")}`;
  return (
    <div className={s.chart} role="img" aria-label={summary} data-motion={animate ? "on" : "off"}>
      <ResponsiveContainer width="100%" height={240} initialDimension={{ width: 320, height: 240 }}>
        <LineChart
          id={id}
          data={[...data]}
          accessibilityLayer
          margin={{ top: 8, right: 16, bottom: 4, left: 4 }}
          onClick={
            onSelect
              ? (state) => {
                  const index = Number(state?.activeIndex);
                  const row = Number.isInteger(index) ? data[index] : undefined;
                  if (row) onSelect(row.key);
                }
              : undefined
          }
        >
          <CartesianGrid stroke={tokens.grid} vertical={false} />
          <XAxis dataKey="label" tick={{ fill: tokens.axis, fontSize: AXIS_FONT }} stroke={tokens.grid} interval="preserveStartEnd" />
          <YAxis allowDecimals={false} width={48} tick={{ fill: tokens.axis, fontSize: AXIS_FONT }} stroke={tokens.grid} />
          <Tooltip formatter={(v) => formatNumber(Number(v))} />
          <Legend wrapperStyle={{ fontSize: AXIS_FONT }} />
          <Line type="monotone" dataKey="a" name={aLabel} stroke={tokens.series[0]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={animate} />
          <Line
            type="monotone"
            dataKey="b"
            name={bLabel}
            stroke={tokens.series[3]}
            strokeWidth={2}
            strokeDasharray="5 3"
            dot={{ r: 3 }}
            isAnimationActive={animate}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** The hearing band colours of row 190 (decision 22): today and tomorrow strong, 2 to 7 days soft, the rest plain. */
export function hearingColour(key: string, t: ChartTokens): string {
  if (key === "today" || key === "tomorrow") return t.strong;
  if (key === "days_2_7") return t.soft;
  if (key === "passed") return t.warning;
  if (key === "none" || key === "disposed") return t.muted;
  return t.plain;
}
