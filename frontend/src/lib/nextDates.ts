/**
 * Plain words for next dates read from orders (design portal-next-dates, decisions 8, 11 and 12): where a date came
 * from, its review status, the one-line hint of a reading rule, an order's reading on the Orders tab, and whether a
 * queue item is a scanned order. Pure functions over the API's codes; no screen shows a rule code, a confidence or a
 * score. An unknown code shows the code with underscores as spaces (the portal's fallback); an unknown rule shows no
 * hint at all.
 */
import type { NextDate, NextDateReviewItem } from "./api/types";
import { formatDate } from "./format";
import { T } from "./messages";

function fallback(code: string): string {
  return code.replace(/_/g, " ");
}

/** The source of a next date in words (`order_period` → "Counted from the order"). */
export function sourceLabel(code: string): string {
  return T.nd.sources[code] ?? fallback(code);
}

/**
 * The review status in words. A pending date reads "Suggested from the order — please confirm" for someone who may
 * answer it and "Waiting for confirmation" for a reader without the action.
 */
export function statusLabel(code: string, { canAct = false }: { canAct?: boolean } = {}): string {
  if (code === "pending" && !canAct) return T.nd.pendingReader;
  return T.nd.statuses[code] ?? fallback(code);
}

/** The one line under a suggested date; null for an unknown or missing rule. */
export function ruleHint(rule: string | null | undefined): string | null {
  if (!rule) return null;
  return T.nd.rules[rule] ?? null;
}

export interface OrderReadingLike {
  next_date_status?: string | null;
  next_date_found?: string | null;
}

export interface Reading {
  /** The date read, formatted; null when none. */
  date: string | null;
  /** The words beside it. */
  words: string;
}

/** Decision 11: an order's own reading, in plain words; null when the API gives no status. */
export function readingLabel(order: OrderReadingLike): Reading | null {
  const status = order.next_date_status;
  if (!status) return null;
  const words = T.nd.reading[status] ?? fallback(status);
  const dated = status === "specific" || status === "period";
  return { date: dated && order.next_date_found ? formatDate(order.next_date_found) : null, words };
}

/**
 * Decision 8: where a next date came from, in one line — "Fixed in the order of 12 Oct 2026", "Counted from the order
 * of 12 Oct 2026 · confirmed by A. Das on 14 Oct 2026", "Entered by A. Das on 14 Oct 2026".
 */
export function originLine(
  row: Pick<NextDate, "source" | "review_status" | "order" | "reviewed_by" | "reviewed_at" | "created_by" | "created_at">,
): string {
  if (row.source === "manual") return T.nd.enteredBy(row.created_by?.name ?? null, formatDate(row.created_at));
  let base: string;
  if (row.source === "order_specific" && row.order) {
    base = T.nd.fixedIn(formatDate(row.order.order_date));
  } else if (row.source === "order_period" && row.order) {
    base = T.nd.countedFrom(formatDate(row.order.order_date));
  } else if (row.source === "causelist") {
    base = T.nd.fromCauselist;
  } else if (row.source === "current_status") {
    base = T.nd.fromCourt;
  } else {
    base = sourceLabel(row.source);
  }
  if (row.review_status === "confirmed" && row.reviewed_at) {
    return `${base} · ${T.nd.confirmedBy(row.reviewed_by?.name ?? null, formatDate(row.reviewed_at))}`;
  }
  return base;
}

/** An *enter* item with neither a rule nor the court's sentence: the order had no readable text (a scan). */
export function isScannedItem(item: Pick<NextDateReviewItem, "kind" | "rule" | "phrase">): boolean {
  return item.kind === "enter" && !item.rule && !item.phrase;
}
