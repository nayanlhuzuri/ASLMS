/**
 * State Insights in the portal (design state-insights, section J, round 2 `state-insights-portal`): the URL is the
 * page's one state. Every filter of decision 24 is a query parameter with the API's own name, so a link can be shared
 * and Back and Forward work; another viewer opening the link sees their own scope's numbers, because the server
 * applies the scope and visibility to every count. The portal builds no label from a code: the chips come from the
 * server. Pure functions only (no React), so the server page and the tests read the same rules.
 */
import type { InsightsOverview } from "./api/types";
import { addDays, istDay } from "./format";
import type { Params } from "./params";
import { queryString } from "./params";

/** The scope, the switch and the two toggles: never removed by a chip or Clear All. */
export const VIEW_KEYS = ["scope", "department", "status", "state_only", "include_ia"] as const;

/** The dimension filters of decision 24, one value each. */
export const DIMENSION_KEYS = [
  "kind",
  "age",
  "next",
  "filed",
  "dept",
  "band",
  "unit",
  "post",
  "subject",
  "counsel",
  "outcome",
  "action",
  "compliance",
  "holder",
] as const;

/** The date filter: Date Of with inclusive IST From and To. */
export const DATE_KEYS = ["date_of", "from", "to"] as const;

/** Every query parameter the Insights API reads besides `page`, `sort`, `format` and `fields`. */
export const FILTER_KEYS: readonly string[] = [...VIEW_KEYS, ...DIMENSION_KEYS, ...DATE_KEYS];

export type DimensionKey = (typeof DIMENSION_KEYS)[number];
export type Status = "pending" | "disposed" | "all";
export const STATUSES: readonly Status[] = ["pending", "disposed", "all"];
export type DateOf = "registration" | "next_hearing" | "latest_order" | "disposal";
export const DATE_OF: readonly DateOf[] = ["registration", "next_hearing", "latest_order", "disposal"];
export type CaseSort = "next" | "registered" | "latest_order";
export const CASE_SORTS: readonly CaseSort[] = ["next", "registered", "latest_order"];
export type Band = "claimed" | "likely" | "named";
export const BANDS: readonly Band[] = ["claimed", "likely", "named"];

/** The case list's page size (decision 26); the server's `page_size` is the same. */
export const CASE_PAGE_SIZE = 20;
/** The PDF row limit the dialog warns about (decision 27, `INSIGHTS_PDF_MAX_ROWS` default). */
export const PDF_ROW_LIMIT = 2000;
/** The overview request waits this long after the last change (decision 32). */
export const OVERVIEW_DEBOUNCE_MS = 300;

/** The page's address: the parameters it reads, in a stable order, and nothing else. */
export function insightsParams(params: Params): Params {
  const out: Params = {};
  for (const key of [...FILTER_KEYS, "page", "sort"]) {
    const value = params[key];
    if (value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

/** The filters the API is asked with (no `page` or `sort`): the overview and the export share them. */
export function filterQuery(params: Params): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of FILTER_KEYS) {
    const value = params[key];
    if (value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

export function insightsHref(params: Params): string {
  return "/insights" + queryString(insightsParams(params));
}

function without(params: Params, keys: readonly string[]): Params {
  const out: Params = {};
  for (const [k, v] of Object.entries(params)) if (!keys.includes(k)) out[k] = v;
  return out;
}

/** Any change of the selection starts the case list again at page 1. */
function fresh(params: Params): Params {
  return without(params, ["page"]);
}

/** Decision 22: a click sets the dimension's value; a click on the value already set removes it. */
export function toggled(params: Params, key: DimensionKey, value: string): Params {
  const next = fresh(params);
  if (params[key] === value) {
    delete next[key];
    if (key === "dept") delete next.band;
  } else {
    next[key] = value;
    if (key === "dept") delete next.band;
  }
  return next;
}

/** A department's band (decision 21): `dept` and `band` together; the same pair again removes both. */
export function bandToggled(params: Params, dept: string, band: Band | null): Params {
  const next = fresh(params);
  if (params.dept === dept && (params.band ?? null) === band) {
    delete next.dept;
    delete next.band;
    return next;
  }
  next.dept = dept;
  if (band) next.band = band;
  else delete next.band;
  return next;
}

/**
 * Decision 23: a holder's click sets `holder` and `action=overdue` as two chips; a second click on the same holder
 * removes the holder (the overdue chip stays until removed on its own).
 */
export function holderToggled(params: Params, office: string): Params {
  const next = fresh(params);
  if (params.holder === office) {
    delete next.holder;
    return next;
  }
  next.holder = office;
  next.action = "overdue";
  return next;
}

/** Removing a chip: `dept` takes its `band` with it, and the date chip (`date_of`) its From and To. */
export function chipRemoved(params: Params, param: string): Params {
  if (param === "date_of") return without(fresh(params), DATE_KEYS);
  if (param === "dept") return without(fresh(params), ["dept", "band"]);
  return without(fresh(params), [param]);
}

/** Clear All: every dimension filter and the dates; the scope, the switch and the toggles stay. */
export function clearedAll(params: Params): Params {
  return without(fresh(params), [...DIMENSION_KEYS, ...DATE_KEYS]);
}

/** A view setting (scope, department, status, the toggles): set, or back to its default when `value` is null. */
export function viewSet(params: Params, key: (typeof VIEW_KEYS)[number], value: string | null): Params {
  const next = fresh(params);
  if (value === null) delete next[key];
  else next[key] = value;
  // a department filter or a unit belongs to one scope; the server would refuse it in the other
  if (key === "scope" || key === "department") {
    delete next.unit;
    if (value === "department" || key === "department") {
      delete next.dept;
      delete next.band;
    }
  }
  return next;
}

export const statusOf = (params: Params): Status =>
  params.status === "disposed" || params.status === "all" ? params.status : "pending";
export const stateOnlyOf = (params: Params): boolean => params.state_only !== "false";
export const includeIaOf = (params: Params): boolean => params.include_ia === "true";

export type HeadlineKey = keyof InsightsOverview["headline"];

/**
 * Decision 22: the headline figures and the filter each click sets. Cases and the two application figures set none.
 * State Cases sets `state_only=true` (the default), so its click is a toggle only when the switch shows all cases.
 */
export const HEADLINE_FILTERS: Partial<Record<HeadlineKey, readonly [DimensionKey | "state_only", string]>> = {
  state_cases: ["state_only", "true"],
  contempt: ["kind", "contempt"],
  over_5_years: ["age", "over_5"],
  hearing_7_days: ["next", "within_7"],
  not_claimed: ["action", "not_claimed"],
};

export const HEADLINE_ORDER: readonly HeadlineKey[] = [
  "cases",
  "state_cases",
  "contempt",
  "over_5_years",
  "hearing_7_days",
  "not_claimed",
];

export function headlineClicked(params: Params, key: HeadlineKey): Params | null {
  const target = HEADLINE_FILTERS[key];
  if (!target) return null;
  const [param, value] = target;
  if (param === "state_only") return viewSet(params, "state_only", null);
  return toggled(params, param, value);
}

export function headlineSelected(params: Params, key: HeadlineKey): boolean {
  const target = HEADLINE_FILTERS[key];
  if (!target) return false;
  const [param, value] = target;
  if (param === "state_only") return stateOnlyOf(params);
  return params[param] === value;
}

/** The first and last day of a month `YYYY-MM`. */
export function monthRange(month: string): { from: string; to: string } {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { from: `${y}-${mm}-01`, to: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

/** Decision 22: a month of "Is the Backlog Growing?" sets Date Of Registration (or Disposal) to that month. */
export function trendClicked(params: Params, month: string, which: "registration" | "disposal"): Params {
  const { from, to } = monthRange(month);
  const next = fresh(params);
  if (params.date_of === which && params.from === from && params.to === to) return without(next, DATE_KEYS);
  return { ...next, date_of: which, from, to };
}

export type QuickDate = "last_30" | "this_year" | "next_7" | "next_30" | "clear";
export const QUICK_DATES: readonly QuickDate[] = ["last_30", "this_year", "next_7", "next_30", "clear"];

/**
 * Decision 24: the quick date choices exist only in the portal and fill Date Of, From and To. Last 30 Days and This
 * Year keep the Date Of chosen (registration when none, or when the next hearing is chosen, whose past is not useful);
 * the two hearing choices set Date Of: Next Hearing.
 */
export function quickDated(params: Params, choice: QuickDate, today: string = istDay()): Params {
  const next = fresh(params);
  if (choice === "clear") return without(next, DATE_KEYS);
  if (choice === "next_7" || choice === "next_30") {
    return { ...next, date_of: "next_hearing", from: today, to: addDays(today, choice === "next_7" ? 7 : 30) };
  }
  const current = params.date_of && params.date_of !== "next_hearing" ? params.date_of : "registration";
  if (choice === "last_30") return { ...next, date_of: current, from: addDays(today, -30), to: today };
  return { ...next, date_of: current, from: `${today.slice(0, 4)}-01-01`, to: today };
}

/** The date bar's own fields: Date Of with From and To; an empty pair clears the dates. */
export function datesSet(params: Params, dateOf: string, from: string, to: string): Params {
  const next = without(fresh(params), DATE_KEYS);
  if (!from && !to) return next;
  return { ...next, date_of: dateOf || "registration", ...(from ? { from } : {}), ...(to ? { to } : {}) };
}

/** True when From is after To (the server answers 400 `bad_dates`; the bar says so before asking). */
export function datesOutOfOrder(from: string | undefined, to: string | undefined): boolean {
  return !!from && !!to && from > to;
}

// ------------------------------------------------------------------------------------------------ the export

export type ExportFormat = "xlsx" | "pdf";
export const EXPORT_STORAGE_KEY = "aslms.insights.export";

/** The export's address through the relay, with exactly the filters and sort of the list on screen. */
export function exportHref(params: Params, format: ExportFormat, fields: readonly string[], sort?: string): string {
  return (
    "/api/backend/insights/export" +
    queryString({ ...filterQuery(params), ...(sort ? { sort } : {}), format, fields: fields.join(",") })
  );
}

/** Decision 33: the export choice kept in the browser for next time (no server state); null when none is kept. */
export function savedFields(storage: Pick<Storage, "getItem"> | null = safeStorage()): string[] | null {
  try {
    const raw = storage?.getItem(EXPORT_STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    return Array.isArray(value) && value.every((v) => typeof v === "string") ? (value as string[]) : null;
  } catch {
    return null;
  }
}

export function saveFields(fields: readonly string[], storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(EXPORT_STORAGE_KEY, JSON.stringify(fields));
  } catch {
    // storage full or refused: the choice is simply not kept
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------------------------------------ the charts

/** The chart cards' "Show All" limits (decision 22): top 10 kinds and counsel codes, top 15 departments. */
export const TOP_KINDS = 10;
export const TOP_COUNSEL = 10;
export const TOP_DEPARTMENTS = 15;

/** The first `n` rows unless every row is asked for. */
export function topRows<R>(rows: readonly R[], n: number, all: boolean): R[] {
  return all ? [...rows] : rows.slice(0, n);
}

/** The words a chart's accessible summary reads: "Today 4, Tomorrow 2 …" (at most 8 parts, then "and n more"). */
export function chartSummary(title: string, parts: readonly { label: string; count: number }[], fmt: (n: number) => string): string {
  const shown = parts.slice(0, 8).map((p) => `${p.label} ${fmt(p.count)}`);
  const more = parts.length > 8 ? `, and ${parts.length - 8} more` : "";
  return parts.length === 0 ? `${title}: no cases` : `${title}: ${shown.join(", ")}${more}`;
}

/** A short form of a long axis label (the full text stays in the tooltip and in View as Table). */
export function shortLabel(text: string, max = 28): string {
  return text.length <= max ? text : text.slice(0, max - 1).trimEnd() + "…";
}

/** The selected bar's label carries a tick, so the choice is never shown by colour alone (decision 31). */
export function tickLabel(text: string, selected: boolean): string {
  return selected ? `✓ ${text}` : text;
}
