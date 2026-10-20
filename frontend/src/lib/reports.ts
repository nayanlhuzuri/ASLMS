/**
 * The Reports screen's pure helpers (design portal-reports, decisions 1 and 3-8): the tabs, the parameters sent to the
 * API with their defaults, the quick period choices in IST, the browser's period checks, the Excel / PDF link and the
 * text of a cell by its column kind. The range limits are the server's settings and are never copied here.
 */
import type { Report, ReportDepartment } from "./api/types";
import { addDays, formatDate, formatNumber } from "./format";
import { T } from "./messages";
import { queryString, type Params } from "./params";

export type ReportKey = "pending-cases" | "hearings-disposals" | "pending-actions" | "data-health";

export interface ReportTab {
  key: ReportKey;
  label: string;
  href: string;
}

/** The four reports in order; which show comes from `GET /reports`, not from a function table. */
export const REPORT_TABS: readonly ReportTab[] = [
  { key: "pending-cases", label: T.tabs.reports.pendingCases, href: "/reports/pending-cases" },
  { key: "hearings-disposals", label: T.tabs.reports.hearingsDisposals, href: "/reports/hearings-disposals" },
  { key: "pending-actions", label: T.tabs.reports.pendingActions, href: "/reports/pending-actions" },
  { key: "data-health", label: T.tabs.reports.dataHealth, href: "/reports/data-health" },
];

export type PeriodChoice = "this_month" | "last_month" | "this_year" | "last_7" | "last_30" | "custom";

export const PERIOD_CHOICES: Record<"hearings-disposals" | "data-health", readonly PeriodChoice[]> = {
  "hearings-disposals": ["this_month", "last_month", "this_year", "custom"],
  "data-health": ["last_7", "last_30", "custom"],
};

export interface Period {
  from: string;
  to: string;
}

/** The dates of a quick choice, `today` being the IST day (`istDay()`); null for "Choose dates". */
export function periodChoice(choice: PeriodChoice, today: string): Period | null {
  const [y, m] = today.split("-");
  const monthStart = `${y}-${m}-01`;
  switch (choice) {
    case "this_month":
      return { from: monthStart, to: today };
    case "last_month": {
      const lastDay = addDays(monthStart, -1);
      return { from: `${lastDay.slice(0, 7)}-01`, to: lastDay };
    }
    case "this_year":
      return { from: `${y}-01-01`, to: today };
    case "last_7":
      return { from: addDays(today, -6), to: today };
    case "last_30":
      return { from: addDays(today, -29), to: today };
    default:
      return null;
  }
}

/** The quick choice the URL's dates stand for (no dates on `data-health`: the API's last 7 days). */
export function choiceOf(key: ReportKey, from: string | undefined, to: string | undefined, today: string): PeriodChoice {
  const choices = key === "data-health" ? PERIOD_CHOICES["data-health"] : PERIOD_CHOICES["hearings-disposals"];
  if (key === "data-health" && !from && !to) return "last_7";
  for (const c of choices) {
    const p = periodChoice(c, today);
    if (p && p.from === from && p.to === to) return c;
  }
  return "custom";
}

export type PeriodProblem = "missing" | "order" | "future";

/** The browser's checks only (decision 5): both dates, `to` not before `from`, `from` not after today. */
export function checkPeriod(from: string | undefined, to: string | undefined, today: string): PeriodProblem | null {
  if (!from || !to) return "missing";
  if (to < from) return "order";
  if (from > today) return "future";
  return null;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function date(value: string | undefined): string | undefined {
  return value && DATE.test(value) ? value : undefined;
}

/**
 * The parameters sent to the API for the URL's parameters (decisions 3-6): `hearings-disposals` defaults to this
 * month; `data-health` sends dates only when the URL has them (else the API's last 7 days) and never a department;
 * `include_cases` only when ticked; empty values omitted.
 */
export function reportParams(key: ReportKey, params: Params, today: string): Params {
  const out: Params = {};
  const set = (k: string, v: string | undefined) => {
    if (v !== undefined && v !== "") out[k] = v;
  };
  if (key !== "data-health") set("department", params.department);
  if (key === "hearings-disposals") {
    const from = date(params.from);
    const to = date(params.to);
    if (from || to) {
      set("from", from);
      set("to", to);
    } else {
      const p = periodChoice("this_month", today)!;
      set("from", p.from);
      set("to", p.to);
    }
  }
  if (key === "data-health") {
    set("from", date(params.from));
    set("to", date(params.to));
  }
  if (key === "pending-actions") {
    set("holder_department", params.holder_department);
    if (params.include_cases === "true") out.include_cases = "true";
  }
  return out;
}

/** The Excel or PDF link of the report shown: the same parameters plus `format`, through the relay. */
export function exportUrl(key: ReportKey, params: Params, format: "xlsx" | "pdf"): string {
  return `/api/backend/reports/${key}${queryString({ ...params, format })}`;
}

/** A cell by its column kind: numbers in the Indian grouping, dates in words, "—" for nothing. */
export function cellText(value: unknown, kind: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "int" || kind === "days") {
    const n = typeof value === "number" ? value : Number(value);
    return Number.isFinite(n) ? formatNumber(n) : String(value);
  }
  if (kind === "date") return formatDate(String(value));
  return String(value);
}

export const WHOLE_STATE = "Whole State";

/** A department's name and code, from the catalogue's names (the code alone when unknown). */
export function departmentLabel(code: string, departments: readonly ReportDepartment[] | undefined): string {
  const d = departments?.find((x) => x.code === code);
  return d ? `${d.name} (${d.code})` : code;
}

/** The scope as the API returned it (`scope`, `department_code`), never as the form shows it. */
export function scopeLabel(
  report: Pick<Report, "scope" | "department_code">,
  departments: readonly ReportDepartment[] | undefined,
): string {
  if (report.scope === "state" || !report.department_code) return WHOLE_STATE;
  return departmentLabel(report.department_code, departments);
}

/** "1 Oct 2026 – 14 Oct 2026". */
export function periodText(from: unknown, to: unknown): string {
  return `${formatDate(String(from))} – ${formatDate(String(to))}`;
}
