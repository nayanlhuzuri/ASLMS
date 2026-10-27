/**
 * Data Collection redesign, round 1 (design data-collection-redesign): the polling rhythm, the query keys and the
 * plain words built from the API's figures, kept apart from the screens so they can be tested alone. Nothing here
 * computes a figure the API did not send; it only words it.
 */
import type { components } from "./api/schema";
import { formatDayLongYear, formatMonthYear, formatNumber } from "./format";
import { T } from "./messages";

type S = components["schemas"];
export type DataOverview = S["DataLoadOverviewOut"];
export type DataPulse = S["DataLoadPulseOut"];
export type DataSchedule = S["DataLoadScheduleOut"];
export type EstimateLine = S["EstimateLineOut"];
export type MonthRow = S["MonthCoverageOut"];

/**
 * Decision 17: the pulse every 5 s, the overview every 30 s (and at once after any action), the month table every
 * 120 s (and on Refresh). Only while the tab is visible: React Query stops interval polling in a hidden tab
 * (`refetchIntervalInBackground: false`) and fetches once when the tab is shown again.
 */
export const POLL = { pulse: 5_000, overview: 30_000, months: 120_000 } as const;

export const DC_KEYS = {
  all: ["data-load"] as const,
  overview: ["data-load", "overview"] as const,
  pulse: ["data-load", "pulse"] as const,
  months: ["data-load", "coverage"] as const,
  schedule: ["data-load", "schedule"] as const,
  progress: ["data-load", "progress"] as const,
};

const n = (value: number | null | undefined) => formatNumber(value ?? 0);

/** `2026-01` → `January 2026`. */
export function monthName(month: string | null | undefined): string {
  if (!month) return "—";
  return formatMonthYear(`${month}-15`);
}

/** The Cause Lists tile's line: where the past-months collection is (decision 14). */
export function causeListsLine(o: Pick<DataOverview, "collection" | "position">): string {
  const month = o.position.working_on_month;
  if (!month) return T.dc.upToDate;
  return o.collection === "paused" ? T.dc.pausedAt(monthName(month)) : T.dc.workingOn(monthName(month));
}

/** The parts of the Problems line with a count above 0 (decision 16). */
export function problemParts(p: DataOverview["problems"]): { key: string; text: string; count: number }[] {
  const counts: [string, number][] = [
    ["failed", p.failed],
    ["duplicates_review", p.duplicates_review],
    ["cases_without_details", p.cases_without_details],
    ["orders_not_available", p.orders_not_available],
  ];
  return counts.filter(([, c]) => c > 0).map(([key, c]) => ({ key, count: c, text: T.dc.problemParts[key]!(n(c)) }));
}

/**
 * Where each part of the Problems line leads. Problems and Fixes arrives in round 2; until then the failed fetches
 * open the queue's failed rows and the duplicates the Duplicates tab, and the two gaps have no page yet.
 */
export const PROBLEM_LINKS: Record<string, string | null> = {
  failed: "/data/queue?status=failed",
  duplicates_review: "/data/duplicates",
  cases_without_details: null,
  orders_not_available: null,
};

/** One estimate line in words (decision 21), never JSON. */
export function estimateText(line: EstimateLine, which: "details" | "all"): string {
  const details = which === "details";
  if (line.reason) {
    const why = T.dc.reasons[line.reason] ?? line.reason;
    return details ? T.dc.estimateDetailsNone(why) : T.dc.estimateAllNone(why);
  }
  if (!line.calls_needed) return details ? T.dc.estimateDetailsDone : T.dc.estimateAllDone;
  const at = formatDayLongYear(line.finish_at);
  return details ? T.dc.estimateDetails(at) : T.dc.estimateAll(at);
}

/** The inputs of the estimate as sentences ("How This Is Worked Out"). */
export function estimateInputs(e: DataOverview["estimate"]): string[] {
  const b = e.basis;
  const rate = (v: number | null | undefined) => (v === null || v === undefined ? T.dc.notMeasured : formatNumber(v));
  return [
    T.dc.howLines.perItem(rate(b.calls_per_item.causelist_day), rate(b.calls_per_item.dossier), rate(b.calls_per_item.order_pdf)),
    T.dc.howLines.spawn(rate(b.dossiers_per_day), rate(b.pdfs_per_dossier)),
    T.dc.howLines.waiting(n(b.pending.causelist_day), n(b.pending.dossier), n(b.pending.order_pdf)),
    T.dc.howLines.needed(
      e.details.calls_needed === null ? T.dc.notMeasured : n(e.details.calls_needed),
      e.all.calls_needed === null ? T.dc.notMeasured : n(e.all.calls_needed),
    ),
    T.dc.howLines.window(b.window_days),
  ];
}

/** The badge tone of a month's state: Not Reached Yet is muted, never red (decision 19). */
export function monthTone(state: string | null | undefined): "success" | "info" | "warning" | undefined {
  if (state === "done") return "success";
  if (state === "in_progress") return "info";
  if (state === "failed_days") return "warning";
  return undefined;
}

/** A month's Still to Fetch in words, or "Nothing" (decision 20). */
export function monthLeft(m: MonthRow): string {
  const left = m.left;
  if (!left) return T.dc.nothingLeft;
  const parts = (["order_pdfs", "days", "cases"] as const)
    .filter((k) => left[k] > 0)
    .map((k) => T.dc.leftParts[k]!(n(left[k])));
  return parts.length ? parts.join(" · ") : T.dc.nothingLeft;
}

/** A month's problems in words: failed days, case details not fetched, failed order PDFs; empty when none. */
export function monthProblems(m: MonthRow): string[] {
  const out: string[] = [];
  if (m.days.failed > 0) out.push(T.dc.monthProblems.days!(n(m.days.failed)));
  if ((m.cases.failed ?? 0) > 0) out.push(T.dc.monthProblems.cases!(n(m.cases.failed)));
  if ((m.orders.failed ?? 0) > 0) out.push(T.dc.monthProblems.pdfs!(n(m.orders.failed)));
  return out;
}

/** The status of a day of the daily cycle (decision 40). */
export function dailyStatus(d: S["DailyCycleDayOut"]): string {
  const st = d.causelist_day?.status;
  if (st === "done") return d.lists_stored > 0 ? T.dc.dailyStatus.done! : T.dc.dailyStatus.none!;
  if (st === "skipped") return T.dc.dailyStatus.none!;
  if (st === "failed") return T.dc.dailyStatus.failed!;
  return T.dc.dailyStatus.waiting!;
}

/** Minutes to the next reset, counted down in the browser from the API's seconds at fetch time. */
export function minutesToReset(seconds: number | null | undefined, fetchedAt: number, now: number): number | null {
  if (seconds === null || seconds === undefined) return null;
  return Math.ceil((seconds - (now - fetchedAt) / 1000) / 60);
}
