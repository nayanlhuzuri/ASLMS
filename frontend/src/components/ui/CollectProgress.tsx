"use client";

/**
 * The progress panel of a collection carried out at once (design data-collection-redesign, decision 25; shared with the
 * case page's Update From the Court, decision 52): the case details step (Waiting, Fetching, Done) and the order PDFs
 * as a segmented bar ("12 of 40 stored · 1 not available at the court") with the time left at the current pace. The
 * active step pulses; under reduced motion nothing moves. Presentational only: the caller passes the figures.
 */
import { T } from "@/lib/messages";

import s from "./collectProgress.module.css";
import { cx } from "./controls";
import { ProgressBar, type ProgressSegment } from "./feedback";

export type CollectStepState = "waiting" | "waiting_retry" | "fetching" | "done" | "not_found" | "failed";

export interface CollectOrders {
  total: number;
  stored: number;
  not_available: number;
  failed: number;
  waiting: number;
}

/** The order PDFs as the bar's segments: stored, being fetched, waiting, not available, failed. */
export function orderSegments(o: CollectOrders, fetching = false): ProgressSegment[] {
  const rest = Math.max(0, o.total - o.stored - o.not_available - o.failed);
  return [
    { tone: "done", value: o.stored },
    { tone: fetching ? "active" : "waiting", value: rest },
    { tone: "unavailable", value: o.not_available },
    { tone: "failed", value: o.failed },
  ];
}

export function CollectProgress({
  details,
  orders,
  etaSeconds,
  label = T.kit.collect.label,
}: {
  /** The case details step; null when the request fetches no details (order PDFs only). */
  details: CollectStepState | null;
  orders: CollectOrders | null;
  etaSeconds?: number | null;
  label?: string;
}) {
  const detailsActive = details === "fetching" || details === "waiting";
  const ordersActive = !detailsActive && !!orders && orders.waiting > 0;
  const minutes = etaSeconds ? Math.max(1, Math.round(etaSeconds / 60)) : null;
  return (
    <section className={s.panel} aria-label={label} data-ui="collect-progress">
      <ol className={s.steps}>
        {details ? (
          <li className={s.step}>
            <span className={s.stepName}>{T.kit.collect.detailsLabel}</span>
            <span className={cx(s.state, s[`state-${details}`], details === "fetching" && s.pulse)} aria-live="polite">
              {T.kit.collect.states[details] ?? details}
            </span>
          </li>
        ) : null}
        <li className={s.step}>
          <span className={s.stepName}>{T.kit.collect.ordersLabel}</span>
          {details && details !== "done" && details !== "not_found" && details !== "failed" ? (
            <span className={s.note}>{T.kit.collect.ordersWaitNote}</span>
          ) : orders && orders.total > 0 ? (
            <span className={cx(s.bar, ordersActive && s.pulse)}>
              <ProgressBar
                segments={orderSegments(orders, ordersActive)}
                max={orders.total}
                label={T.kit.collect.ordersLabel}
                text={T.kit.collect.ordersText(orders.stored, orders.total, orders.not_available, orders.failed)}
              />
            </span>
          ) : (
            <span className={s.note}>{T.kit.collect.ordersNone}</span>
          )}
        </li>
      </ol>
      {minutes ? <p className={s.note}>{T.kit.collect.etaNote(minutes)}</p> : null}
    </section>
  );
}
