"use client";

/**
 * Feedback of the UI kit (design portal-ui-redesign, decisions 10.6, 10.14, 11, 17 and 19): badges with fixed colour
 * meanings, the error banner with Retry, notices, skeletons while loading (with the visually hidden "Loading" status
 * text), empty states with an icon circle and a title, the score and severity badges, signal chips, the meter and
 * the stepper. Colour is never the only signal: every badge carries words.
 */
import type { ReactNode } from "react";

import { errorText, T, type ErrorTexts } from "@/lib/messages";
import { signalText, type Signal } from "@/lib/signals";

import { Button, cx } from "./controls";
import s from "./feedback.module.css";

/** Red = urgent or overdue; amber = due soon; green = done or confirmed; blue (`info`) = action; none = neutral. */
export type Tone = "danger" | "warning" | "success" | "info";

export function Badge({ tone, title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span className={cx(s.badge, tone && s[`badge-${tone}`])} title={title ?? (typeof children === "string" ? children : undefined)}>
      <span className={s.badgeText}>{children}</span>
    </span>
  );
}

export function ErrorBanner({
  error,
  onRetry,
  messages,
  children,
  retrySize = "sm",
}: {
  error: unknown;
  onRetry?: () => void;
  /** The screen's own texts for codes that mean something else elsewhere (design portal-workflow, decision 21). */
  messages?: ErrorTexts;
  /** More after the message (a link to an existing document, for example). */
  children?: ReactNode;
  /** The Try again button's size: `sm` by default; `md` where it stands alone, outside a row (followups-oct, 14). */
  retrySize?: "sm" | "md";
}) {
  if (!error) return null;
  return (
    <div className={s.banner} role="alert" aria-live="assertive">
      <span>{errorText(error, messages)}</span>
      {children}
      {onRetry ? (
        <Button variant="secondary" size={retrySize} onClick={onRetry}>
          {T.retry}
        </Button>
      ) : null}
    </div>
  );
}

/** A short message in the page; `tone="warning"` (amber) for something to report or act on. */
export function Notice({ children, tone }: { children: ReactNode; tone?: "warning" }) {
  return (
    <div className={s.notice} role="status" aria-live="polite" data-tone={tone}>
      {children}
    </div>
  );
}

/** Grey shimmering bars in the shape of the content; hidden from screen readers. */
export function Skeleton({ lines = 3, width }: { lines?: number; width?: string }) {
  return (
    <span className={s.skeletonGroup} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className={s.skeleton} style={width ? { width } : undefined} />
      ))}
    </span>
  );
}

/** While a list or panel loads: skeleton rows and the visually hidden status text "Loading…". */
export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <span className={s.loading} role="status" aria-live="polite">
      <span className="visually-hidden">{T.loading}</span>
      <Skeleton lines={lines} />
    </span>
  );
}

function EmptyIcon() {
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 13h5l1 3h6l1-3h5" />
      <path d="M5 13 7 5h10l2 8v6H5z" />
    </svg>
  );
}

/** An empty list: the icon circle, an optional title, and one line saying when items appear. */
export function EmptyState({ title, icon, children }: { title?: ReactNode; icon?: ReactNode; children?: ReactNode }) {
  return (
    <div className={s.empty}>
      <span className={s.emptyIcon}>{icon ?? <EmptyIcon />}</span>
      {title ? <p className={s.emptyTitle}>{title}</p> : null}
      {children ? <div className={s.emptyText}>{children}</div> : null}
    </div>
  );
}

/**
 * The score as stored (three decimals) with the label of the API's `band`: "Strong · 0.950" in blue for `high`,
 * "Possible · 0.620" in neutral for `medium` (decision 10.6). The colour and the label never come from the portal
 * comparing numbers, because the bands are the super admin's settings.
 */
export function ScoreBadge({ score, band }: { score: number; band: string }) {
  const known = (T.score as Record<string, unknown>)[band];
  const label = band === "high" || band === "medium" ? (known as string) : band.charAt(0).toUpperCase() + band.slice(1);
  return <Badge tone={band === "high" ? "info" : undefined}>{T.score.badge(label, score.toFixed(3))}</Badge>;
}

/** The API's severity of an alert (critical / high / normal), never computed in the browser. */
export function SeverityBadge({ severity }: { severity: string }) {
  const tone = severity === "critical" ? "danger" : severity === "high" ? "warning" : undefined;
  return <Badge tone={tone}>{T.wf.severity[severity] ?? severity}</Badge>;
}

export function SignalChip({ signal }: { signal: Signal }) {
  return <span className={s.signal}>{signalText(signal)}</span>;
}

export function SignalChips({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  return (
    <ul className={s.signals} aria-label={T.kit.signals}>
      {signals.map((sig, i) => (
        <li key={i}>
          <SignalChip signal={sig} />
        </li>
      ))}
    </ul>
  );
}

/** A filled bar for a value from 0 to 1 (the match strength), filling over 700 ms. */
export function Meter({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className={s.meter} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={v}>
      <i className={s.meterFill} style={{ width: `${(v * 100).toFixed(1)}%` }} />
    </div>
  );
}

/** The progress bars of a stepped dialog and its "Step n of 3 · …" line (decision 25). */
export function Stepper({ step, steps }: { step: number; steps: string[] }) {
  const current = Math.max(1, Math.min(step, steps.length));
  return (
    <div className={s.stepper}>
      <div className={s.steps} aria-hidden="true">
        {steps.map((label, i) => (
          <span key={label} className={cx(s.step, i < current && s.stepDone)}>
            <i />
          </span>
        ))}
      </div>
      <p className={s.stepLabel} aria-live="polite">
        {T.kit.step(current, steps.length, steps[current - 1] ?? "")}
      </p>
    </div>
  );
}

/** The tones of a progress segment (design data-collection-redesign, decision 9). */
export type ProgressTone = "done" | "active" | "waiting" | "unavailable" | "failed";

export interface ProgressSegment {
  tone: ProgressTone;
  value: number;
}

const PROGRESS_ORDER: readonly ProgressTone[] = ["done", "active", "waiting", "unavailable", "failed"];

/**
 * A segmented progress bar (decision 9): done is solid green, active the accent with the live pulse, waiting striped
 * accent-soft, unavailable slate with a strong edge, failed red. `role="progressbar"` with the done amount as
 * `aria-valuenow` of `max` and `text` as `aria-valuetext`; the same text is shown under the bar (never colour alone)
 * unless the caller shows it beside the bar (`showText={false}`). Each segment grows by `scaleX` over `--slow`; under
 * reduced motion nothing animates. Nothing moves the layout.
 */
export function ProgressBar({
  segments,
  max,
  label,
  text,
  size = "md",
  showText = true,
}: {
  segments: ProgressSegment[];
  /** The whole (defaults to the sum of the segments). */
  max?: number;
  label: string;
  text: string;
  size?: "sm" | "md";
  showText?: boolean;
}) {
  const total = Math.max(0, max ?? segments.reduce((sum, seg) => sum + Math.max(0, seg.value), 0));
  const done = segments.filter((seg) => seg.tone === "done").reduce((sum, seg) => sum + Math.max(0, seg.value), 0);
  const ordered = [...segments].sort((a, b) => PROGRESS_ORDER.indexOf(a.tone) - PROGRESS_ORDER.indexOf(b.tone));
  // the segments never add up past the whole, so the track never holds more than it shows
  let room = 100;
  const widths = ordered.map((seg) => {
    const w = total > 0 ? Math.max(0, Math.min(room, (Math.max(0, seg.value) / total) * 100)) : 0;
    room -= w;
    return w;
  });
  return (
    <div className={s.progress}>
      <div
        className={cx(s.progressTrack, size === "sm" ? s.progressSm : s.progressMd)}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={Math.min(done, total)}
        aria-valuetext={text}
      >
        {total > 0
          ? ordered.map((seg, i) =>
              widths[i]! > 0 ? (
                <i
                  key={seg.tone}
                  className={cx(s.progressSeg, s[`seg-${seg.tone}`])}
                  data-tone={seg.tone}
                  style={{ width: `${widths[i]!.toFixed(2)}%` }}
                />
              ) : null,
            )
          : null}
      </div>
      {showText ? <span className={s.progressText}>{text}</span> : null}
    </div>
  );
}

/** The legend of a segmented bar: a swatch per tone with its words (and count when given). */
export function ProgressLegend({ items }: { items: { tone: ProgressTone; label: string; value?: string }[] }) {
  return (
    <ul className={s.legend} aria-label={T.kit.legend}>
      {items.map((it) => (
        <li key={it.tone}>
          <i className={cx(s.swatch, s[`seg-${it.tone}`])} aria-hidden="true" />
          <span>{it.label}</span>
          {it.value !== undefined ? <b>{it.value}</b> : null}
        </li>
      ))}
    </ul>
  );
}
