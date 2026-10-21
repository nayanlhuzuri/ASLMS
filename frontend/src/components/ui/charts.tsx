"use client";

/**
 * Small inline-SVG charts (design api-health-checker, decision 15), with no chart library: `SparkBars` (stacked bars
 * of answered and failed calls per bucket), `RateRing` (a donut of a rate from 0 to 1 with words inside) and
 * `StatusDot` (a status colour that may pulse). Colour is never the only signal: each carries an accessible name and
 * the screens print the words beside them. Motion follows decision 13: bars grow from the baseline with a 10 ms
 * stagger and the ring sweeps in 700 ms; under reduced motion everything is drawn at its final value at once.
 */
import type { CSSProperties, ReactNode } from "react";

import { cx } from "./controls";
import s from "./charts.module.css";
import { usePrefersReducedMotion } from "./motion";

export interface BarBucket {
  answered: number;
  failed: number;
}

/** Stacked bars: answered (green) at the base, failed (red) on top, scaled to the busiest bucket. */
export function SparkBars({
  buckets,
  label,
  height = 36,
}: {
  buckets: BarBucket[];
  label: string;
  height?: number;
}) {
  const reduced = usePrefersReducedMotion();
  const max = Math.max(1, ...buckets.map((b) => b.answered + b.failed));
  const n = Math.max(1, buckets.length);
  const step = 100 / n;
  const width = step * 0.7;
  return (
    <svg
      className={cx(s.spark, !reduced && s.animate)}
      role="img"
      aria-label={label}
      viewBox={`0 0 100 ${height}`}
      preserveAspectRatio="none"
      height={height}
      data-motion={reduced ? "off" : "on"}
    >
      {buckets.map((b, i) => {
        const ok = (b.answered / max) * height;
        const bad = (b.failed / max) * height;
        const x = i * step + (step - width) / 2;
        const style = reduced ? undefined : ({ animationDelay: `${i * 10}ms` } as CSSProperties);
        return (
          <g key={i} className={s.bar} style={style} data-testid="spark-bar">
            {ok > 0 ? <rect className={s.ok} x={x} y={height - ok} width={width} height={ok} rx={0.6} /> : null}
            {bad > 0 ? (
              <rect className={s.bad} x={x} y={height - ok - bad} width={width} height={bad} rx={0.6} />
            ) : null}
            {ok + bad === 0 ? <rect className={s.empty} x={x} y={height - 1} width={width} height={1} /> : null}
          </g>
        );
      })}
    </svg>
  );
}

const RING_R = 42;
const RING_C = 2 * Math.PI * RING_R;

/** A donut of `value` (0 to 1, null: nothing to show) in a status tone, with `children` (the words) inside. */
export function RateRing({
  value,
  label,
  tone = "ok",
  children,
  size = 128,
}: {
  value: number | null | undefined;
  label: string;
  tone?: "ok" | "warn" | "down" | "unknown";
  children?: ReactNode;
  size?: number;
}) {
  const reduced = usePrefersReducedMotion();
  const v = typeof value === "number" ? Math.max(0, Math.min(1, value)) : 0;
  const offset = RING_C * (1 - v);
  return (
    <div className={s.ring} style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden="true" data-motion={reduced ? "off" : "on"}>
        <circle className={s.track} cx="50" cy="50" r={RING_R} />
        {typeof value === "number" ? (
          <circle
            className={cx(s.sweep, s[`tone-${tone}`], !reduced && s.animate)}
            cx="50"
            cy="50"
            r={RING_R}
            strokeDasharray={RING_C.toFixed(2)}
            strokeDashoffset={offset.toFixed(2)}
            style={{ "--ring-c": RING_C.toFixed(2) } as CSSProperties}
            data-testid="ring-sweep"
          />
        ) : null}
      </svg>
      <div className={s.ringText} aria-hidden="true">
        {children}
      </div>
    </div>
  );
}

/** A status dot; `pulse` makes it beat while something runs (still under reduced motion). */
export function StatusDot({ tone = "unknown", pulse }: { tone?: "ok" | "warn" | "down" | "unknown" | "busy"; pulse?: boolean }) {
  const reduced = usePrefersReducedMotion();
  return <span className={cx(s.dot, s[`dot-${tone}`], pulse && !reduced && s.pulse)} aria-hidden="true" data-testid="status-dot" />;
}
