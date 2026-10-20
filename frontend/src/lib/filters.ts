/**
 * The one filter bar's rules (design portal-filters, decisions 1, 2, 9-13), kept in a plain module so server pages
 * and tests can import its values. The URL keys are the API's names; the cause-list and next-hearing dates may be a
 * preset (`listed=today|tomorrow|d7|d30`, `next=today|n7|n30`, worked out in IST each time the page opens) or explicit
 * dates (`listed_from` / `listed_to`, `next_from` / `next_to`), and explicit dates win over a preset.
 */
import { addDays, formatDate, istDay } from "./format";
import type { Params } from "./params";

/** The shared fields a list may declare (decision 11). */
export type SharedField =
  | "q"
  | "listed"
  | "next"
  | "case_type"
  | "year"
  | "case_status"
  | "court_no"
  | "bench"
  | "owner"
  | "scored_for"
  | "other_office";

export type ListKey =
  | "recommended"
  | "claimed_active"
  | "claimed_disposed"
  | "pool"
  | "transfers"
  | "held"
  | "held_owned"
  | "sent"
  | "alerts"
  | "search"
  | "documents"
  | "next_dates"
  | "mine"
  | "department";

/** Every URL key of the shared fields. */
export const FILTER_KEYS = [
  "q",
  "listed",
  "listed_from",
  "listed_to",
  "next",
  "next_from",
  "next_to",
  "case_type",
  "year",
  "case_status",
  "court_no",
  "bench",
  "owner",
  "scored_for",
  "other_office",
] as const;

/** The URL keys of each field. */
export const FIELD_KEYS: Record<SharedField, readonly string[]> = {
  q: ["q"],
  listed: ["listed", "listed_from", "listed_to"],
  next: ["next", "next_from", "next_to"],
  case_type: ["case_type"],
  year: ["year"],
  case_status: ["case_status"],
  court_no: ["court_no"],
  bench: ["bench"],
  owner: ["owner"],
  scored_for: ["scored_for"],
  other_office: ["other_office"],
};

/** The fields under "More filters" (decision 9); the others are on the first row. */
export const MORE_FIELDS: readonly SharedField[] = ["year", "case_status", "court_no", "bench", "owner", "scored_for", "other_office"];

const ALL_CASE: SharedField[] = ["q", "listed", "next", "case_type", "year", "case_status", "court_no", "bench"];

export interface ListFilters {
  /** The shared fields the list shows. */
  fields: readonly SharedField[];
  /** The tab's own fixed keys, kept by "Clear all". */
  fixed: readonly string[];
  /** Old URL names read once as the new ones (decision 13). */
  legacy?: Readonly<Record<string, string>>;
  /** The fields under "More filters" (default `MORE_FIELDS`; design portal-ui-redesign, decision 5). */
  more?: readonly SharedField[];
  /** Fields applied and shown as chips but not drawn in the form (a quick chip sets them). */
  hidden?: readonly SharedField[];
  /** The next-hearing choices (default `NEXT_PRESETS` with "A date" and "Between dates"). */
  nextChoices?: readonly string[];
}

/** The fields under "More filters" of a list. */
export function moreFieldsOf(list: ListKey): readonly SharedField[] {
  return LIST_FILTERS[list].more ?? MORE_FIELDS;
}

/** Decision 11: which shared fields each list shows. */
export const LIST_FILTERS: Record<ListKey, ListFilters> = {
  recommended: { fields: ALL_CASE, fixed: ["department"] },
  claimed_active: { fields: ALL_CASE.filter((f) => f !== "case_status"), fixed: ["department", "case_state"] },
  claimed_disposed: {
    fields: ALL_CASE.filter((f) => f !== "case_status" && f !== "next"),
    fixed: ["department", "case_state"],
  },
  pool: { fields: [...ALL_CASE, "scored_for"], fixed: ["department"], legacy: { status: "case_status" } },
  transfers: { fields: [...ALL_CASE, "other_office"], fixed: ["department", "direction"] },
  held: { fields: [...ALL_CASE, "owner"], fixed: [] },
  held_owned: { fields: [...ALL_CASE, "owner"], fixed: [] },
  sent: { fields: [...ALL_CASE, "owner"], fixed: [] },
  alerts: { fields: [...ALL_CASE, "owner"], fixed: [] },
  search: { fields: [...ALL_CASE, "owner"], fixed: ["tab"], legacy: { status: "case_status", office: "owner" } },
  documents: { fields: ["q"], fixed: ["tab"] },
  // design portal-next-dates, decision 4: the review list's own control is "Show" (`kind`)
  next_dates: { fields: [...ALL_CASE, "owner"], fixed: ["kind"] },
  // design portal-ui-redesign, decision 5: the Case inbox views (quick chips for the next hearing and the action,
  // Stage, then words, case type, year and court under "More filters")
  mine: {
    fields: ["q", "next", "case_type", "year", "court_no"],
    fixed: [],
    more: ["q", "case_type", "year", "court_no"],
    hidden: ["next"],
  },
  // Department cases: Search, Unit, Officer, Stage, Next hearing; More: case type, year, court, file holder, action
  department: {
    fields: ["q", "next", "case_type", "year", "court_no"],
    fixed: ["department", "case_state"],
    more: ["case_type", "year", "court_no"],
    nextChoices: ["", "n7", "n30", "range"],
  },
};

export const LISTED_PRESETS = ["today", "tomorrow", "d7", "d30"] as const;
export const NEXT_PRESETS = ["today", "n7", "n30"] as const;
export const CASE_STATUSES = ["pending", "disposed", "unknown"] as const;
export const MIN_WORDS = 3;
export const MIN_BENCH = 3;
export const MAX_BENCH = 200;

/** Decision 13: on Search and the pool an old `status=` (and on Search `office=`) is read as the new key, once. */
export function legacyParams(params: Params, list: ListKey): Params {
  const legacy = LIST_FILTERS[list].legacy;
  if (!legacy) return params;
  const out: Params = { ...params };
  for (const [old, now] of Object.entries(legacy)) {
    const value = out[old];
    if (value === undefined || value === "") continue;
    if (!out[now]) out[now] = value;
    delete out[old];
  }
  return out;
}

function presetRange(kind: "listed" | "next", preset: string | undefined, today: string): [string, string] | null {
  if (kind === "listed") {
    if (preset === "today") return [today, today];
    if (preset === "tomorrow") return [addDays(today, 1), addDays(today, 1)];
    if (preset === "d7") return [addDays(today, -6), today];
    if (preset === "d30") return [addDays(today, -29), today];
    return null;
  }
  if (preset === "today") return [today, today];
  if (preset === "n7") return [today, addDays(today, 6)];
  if (preset === "n30") return [today, addDays(today, 29)];
  return null;
}

export interface Dates {
  listed_from?: string;
  listed_to?: string;
  next_from?: string;
  next_to?: string;
}

/** Decision 10: presets to IST dates (explicit dates win over a preset). */
export function resolveDates(params: Params, now: Date = new Date()): Dates {
  const today = istDay(now);
  const out: Dates = {};
  for (const kind of ["listed", "next"] as const) {
    const from = params[`${kind}_from`] || undefined;
    const to = params[`${kind}_to`] || undefined;
    if (from || to) {
      if (from) out[`${kind}_from`] = from;
      if (to) out[`${kind}_to`] = to;
      continue;
    }
    const range = presetRange(kind, params[kind], today);
    if (range) {
      out[`${kind}_from`] = range[0];
      out[`${kind}_to`] = range[1];
    }
  }
  return out;
}

/** The API query of the shared fields the list allows (the list adds its own controls). */
export function toApiQuery(params: Params, list: ListKey, now: Date = new Date()): Record<string, string | undefined> {
  const p = legacyParams(params, list);
  const fields = LIST_FILTERS[list].fields;
  const dates = resolveDates(p, now);
  const out: Record<string, string | undefined> = {};
  for (const field of fields) {
    if (field === "listed" || field === "next") {
      out[`${field}_from`] = dates[`${field}_from`];
      out[`${field}_to`] = dates[`${field}_to`];
    } else {
      const v = (p[field] ?? "").trim();
      out[field] = v || undefined;
    }
  }
  return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined));
}

/** Whether any shared field of the list is set in the URL (the Alerts list's case-less line, decision 8). */
export function hasCaseFilter(params: Params, list: ListKey): boolean {
  const p = legacyParams(params, list);
  return LIST_FILTERS[list].fields.some((f) => FIELD_KEYS[f].some((k) => !!p[k]));
}

// ------------------------------------------------------------------------------------------------ the form

export type DateMode = "" | "date" | "range" | (typeof LISTED_PRESETS)[number] | (typeof NEXT_PRESETS)[number];

/** The date field of the form: a preset, "A date" or "Between dates" with its inputs. */
export function dateModeOf(params: Params, kind: "listed" | "next"): { mode: DateMode; from: string; to: string } {
  const from = params[`${kind}_from`] ?? "";
  const to = params[`${kind}_to`] ?? "";
  if (from || to) return { mode: from && from === to ? "date" : "range", from, to };
  const presets: readonly string[] = kind === "listed" ? LISTED_PRESETS : NEXT_PRESETS;
  const preset = params[kind] ?? "";
  return { mode: presets.includes(preset) ? (preset as DateMode) : "", from: "", to: "" };
}

/** The form values as URL keys: a preset as `listed=` / `next=`, "A date" as both ends equal. */
export function dateParams(kind: "listed" | "next", mode: DateMode, from: string, to: string): Params {
  const out: Params = { [kind]: undefined, [`${kind}_from`]: undefined, [`${kind}_to`]: undefined };
  if (mode === "date") {
    out[`${kind}_from`] = from || undefined;
    out[`${kind}_to`] = from || undefined;
  } else if (mode === "range") {
    out[`${kind}_from`] = from || undefined;
    out[`${kind}_to`] = to || undefined;
  } else if (mode) {
    out[kind] = mode;
  }
  return out;
}

export interface FilterForm {
  q?: string;
  listed?: { mode: DateMode; from: string; to: string };
  next?: { mode: DateMode; from: string; to: string };
  year?: string;
  bench?: string;
  /** Extra date pairs to check (a list's own range, e.g. the document date). */
  ranges?: { key: string; from: string; to: string }[];
}

export interface FilterTexts {
  reversed: string;
  chooseDate: string;
  year: string;
  words: string;
  bench: string;
}

/** Decision 7 in the browser: the same checks as the server, so a bad filter is never sent. Keys: the field whose
 * input shows the error (`listed_to`, `next_to`, `listed_from` for a missing date, `year`, `q`, `bench`). */
export function validate(form: FilterForm, texts: FilterTexts): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const kind of ["listed", "next"] as const) {
    const d = form[kind];
    if (!d) continue;
    if (d.mode === "date" && !d.from) errors[`${kind}_from`] = texts.chooseDate;
    if (d.mode === "range" && d.from && d.to && d.from > d.to) errors[`${kind}_to`] = texts.reversed;
    if (d.mode === "range" && !d.from && !d.to) errors[`${kind}_from`] = texts.chooseDate;
  }
  for (const r of form.ranges ?? []) {
    if (r.from && r.to && r.from > r.to) errors[r.key] = texts.reversed;
  }
  const year = (form.year ?? "").trim();
  if (year && !(/^\d{4}$/.test(year) && Number(year) >= 1900 && Number(year) <= 2100)) errors.year = texts.year;
  const q = (form.q ?? "").trim();
  if (q && (q.length < MIN_WORDS || !/[0-9A-Za-z]{2}/.test(q))) errors.q = texts.words;
  const bench = (form.bench ?? "").trim().replace(/\s+/g, " ");
  if (bench && (bench.length < MIN_BENCH || bench.length > MAX_BENCH)) errors.bench = texts.bench;
  return errors;
}

// ------------------------------------------------------------------------------------------------ chips

export interface Chip {
  /** The URL keys the chip's remove button drops. */
  keys: string[];
  label: string;
}

export interface ChipTexts {
  field: Record<SharedField, string>;
  listedPresets: Record<string, string>;
  nextPresets: Record<string, string>;
  statuses: Record<string, string>;
  range: (from: string, to: string) => string;
  from: (d: string) => string;
  to: (d: string) => string;
}

function dateChip(params: Params, kind: "listed" | "next", texts: ChipTexts): string | null {
  const { mode, from, to } = dateModeOf(params, kind);
  if (!mode) return null;
  if (mode === "date") return formatDate(from);
  if (mode === "range") {
    if (from && to) return texts.range(formatDate(from), formatDate(to));
    return from ? texts.from(formatDate(from)) : texts.to(formatDate(to));
  }
  return (kind === "listed" ? texts.listedPresets : texts.nextPresets)[mode] ?? mode;
}

/** One chip per applied shared field of the list, in the bar's order. */
export function chipsOf(params: Params, list: ListKey, texts: ChipTexts): Chip[] {
  const p = legacyParams(params, list);
  const legacy = Object.keys(LIST_FILTERS[list].legacy ?? {});
  const out: Chip[] = [];
  for (const field of LIST_FILTERS[list].fields) {
    const keys = [...FIELD_KEYS[field]];
    let value: string | null;
    if (field === "listed" || field === "next") value = dateChip(p, field, texts);
    else if (field === "case_status") value = p.case_status ? (texts.statuses[p.case_status] ?? p.case_status) : null;
    else value = (p[field] ?? "").trim() || null;
    if (!value) continue;
    // a chip of a field read from an old name also drops the old name
    for (const old of legacy) if (LIST_FILTERS[list].legacy![old] === field) keys.push(old);
    out.push({ keys, label: `${texts.field[field]}: ${value}` });
  }
  return out;
}
