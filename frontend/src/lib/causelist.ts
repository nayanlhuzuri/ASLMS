/**
 * The Cause list screen's plain helpers (design portal-causelist, decisions 3, 8 and 11): the URL keys and their API
 * query, the heading breaks of the court order, and the labels of bands, day states and list types. A plain module
 * (no "use client"), so the server page and the tests import values, not client references.
 */
import type { CauselistBench as Bench } from "./api/types";
import type { Params } from "./params";

export const ONLY_VALUES = ["recommended", "mine", "claimable", "unclaimed", "claimed", "visible"] as const;
export type Only = (typeof ONLY_VALUES)[number];
export const LIST_TYPES = ["daily", "supplementary", "lawazima", "vacation", "other"] as const;
export const DAY_STATES = ["held", "loading", "no_list", "failed", "not_loaded"] as const;
/** Day states on which holders of `admin.napix_refetch` may ask for the day from the court (decision 5). */
export const FETCHABLE_STATES: readonly string[] = ["not_loaded", "failed", "no_list"];
/** One page of entries (the API allows up to 500; one bench's lists are rarely longer). */
export const ENTRY_PAGE = 200;
export const MIN_WORDS = 3;
/** The URL keys of the screen, so a bookmarked or shared list reopens as it was (decision 11). */
export const URL_KEYS = ["date", "bench_id", "list_id", "list_type", "court_no", "q", "only", "offset"] as const;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function validDate(value: string | undefined): string | undefined {
  return value && ISO_DATE.test(value) ? value : undefined;
}

function offsetOf(params: Params): number {
  const n = Number(params.offset ?? 0);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

/**
 * The URL's keys as the query of `GET /causelists/{date}/entries` (the date is the path): `bench_id` or `list_id`
 * (a bench wins when an edited URL has both), the list type and `only` when they are known values, the court number
 * trimmed, words of at least three characters, and the page.
 */
export function toApiQuery(params: Params): Record<string, string | number | undefined> {
  const bench = (params.bench_id ?? "").trim();
  const list = (params.list_id ?? "").trim();
  const listType = (params.list_type ?? "").trim().toLowerCase();
  const only = (params.only ?? "").trim().toLowerCase();
  const court = (params.court_no ?? "").trim();
  const q = (params.q ?? "").trim();
  const benchId = /^\d+$/.test(bench) ? bench : undefined;
  return {
    bench_id: benchId,
    list_id: !benchId && UUID.test(list) ? list : undefined,
    list_type: (LIST_TYPES as readonly string[]).includes(listType) ? listType : undefined,
    court_no: court || undefined,
    q: q.length >= MIN_WORDS ? q : undefined,
    only: (ONLY_VALUES as readonly string[]).includes(only) ? only : undefined,
    limit: ENTRY_PAGE,
    offset: offsetOf(params),
  };
}

/** What a heading row needs of an entry. */
export interface HeadingSource {
  court_no: string | null;
  bench_id: number | null;
  bench_label: string | null;
  causelist_id: string;
  list_type: string;
  section: string | null;
}

export type HeadingKind = "court" | "bench" | "list" | "section";

export interface Heading {
  kind: HeadingKind;
  text: string;
}

const LEVELS: HeadingKind[] = ["court", "bench", "list", "section"];

function levelValue(e: HeadingSource, kind: HeadingKind): string {
  switch (kind) {
    case "court":
      return (e.court_no ?? "").trim();
    case "bench":
      return `${e.bench_id ?? ""}|${e.bench_label ?? ""}`;
    case "list":
      return e.causelist_id;
    case "section":
      return (e.section ?? "").trim();
  }
}

export interface HeadingTexts {
  court: (court: string | null) => string;
  bench: (label: string | null, benchId: number | null) => string;
  list: (listType: string) => string;
}

/**
 * Decision 3: the heading rows to draw before each entry, in API order. A change of court redraws the bench, list and
 * section headings under it; a change of bench redraws the list and section; and so on. A section heading is drawn
 * only for a printed section.
 */
export function headingsOf(items: HeadingSource[], texts: HeadingTexts): Heading[][] {
  const out: Heading[][] = [];
  let prev: HeadingSource | null = null;
  for (const e of items) {
    const from = prev === null ? 0 : LEVELS.findIndex((k) => levelValue(e, k) !== levelValue(prev!, k));
    const heads: Heading[] = [];
    if (from >= 0) {
      for (const kind of LEVELS.slice(from)) {
        if (kind === "court") heads.push({ kind, text: texts.court(e.court_no?.trim() || null) });
        if (kind === "bench") heads.push({ kind, text: texts.bench(e.bench_label, e.bench_id) });
        if (kind === "list") heads.push({ kind, text: texts.list(e.list_type) });
        if (kind === "section" && (e.section ?? "").trim()) heads.push({ kind, text: e.section!.trim() });
      }
    }
    out.push(heads);
    prev = e;
  }
  return out;
}

/** The API's band as the screen names it (the bands are the super admin's settings; the portal never compares). */
export function bandLabel(band: string): string {
  if (band === "high") return "Strong";
  if (band === "medium") return "Possible";
  return band;
}

/** "Strong · EDU · 0.95" */
export function recommendationText(r: { office_code: string; band: string; score: number }): string {
  return `${bandLabel(r.band)} · ${r.office_code} · ${r.score.toFixed(2)}`;
}

/** The value of the bench select for a bench (`b:<bench id>`, or `l:<list id>` for a court-wide file). */
export function benchValue(b: Bench): string {
  if (b.bench_id !== null) return `b:${b.bench_id}`;
  return b.lists[0] ? `l:${b.lists[0].id}` : "";
}

/** The bench select's value from the URL. */
export function benchValueOf(params: Params): string {
  const query = toApiQuery(params);
  if (query.bench_id) return `b:${query.bench_id}`;
  if (query.list_id) return `l:${query.list_id}`;
  return "";
}

/** The URL keys for a bench select value. */
export function benchParams(value: string): Params {
  if (value.startsWith("b:")) return { bench_id: value.slice(2), list_id: undefined };
  if (value.startsWith("l:")) return { bench_id: undefined, list_id: value.slice(2) };
  return { bench_id: undefined, list_id: undefined };
}

/** The bench chosen by the URL among the day's benches, if any. */
export function chosenBench(benches: Bench[], params: Params): Bench | null {
  const value = benchValueOf(params);
  if (!value) return null;
  return benches.find((b) => benchValue(b) === value) ?? null;
}

/** The cause list of a listing's day and bench (decision 12; the date only for a court-wide file). */
export function causelistHref(listDate: string, benchId: number | null | undefined): string {
  const qs = new URLSearchParams({ date: listDate });
  if (benchId !== null && benchId !== undefined) qs.set("bench_id", String(benchId));
  return `/causelist?${qs.toString()}`;
}

/** One page of the View Cause List modal's printed entries (design portal-ui-polish-2, decision 25). */
export const VIEW_PAGE = 100;

/** The tabs of the View Cause List modal (`vtab`). */
export const VIEW_TABS = ["entries", "pdf"] as const;
export type ViewTab = (typeof VIEW_TABS)[number];

/** The `view` value of a bench: its bench id, or a court-wide file's list id. */
export function viewValue(b: Bench): string {
  if (b.bench_id !== null) return String(b.bench_id);
  return b.lists[0]?.id ?? "";
}

/** The bench the `view` value names among the day's benches, if any. */
export function benchOfView(benches: Bench[], value: string | null | undefined): Bench | null {
  if (!value) return null;
  return benches.find((b) => viewValue(b) === value) ?? null;
}

/** The entries query of a `view` value: `bench_id` for a bench, `list_id` for a court-wide file. */
export function viewQuery(value: string, offset: number): Record<string, string | number | undefined> {
  const bench = /^\d+$/.test(value);
  return {
    bench_id: bench ? value : undefined,
    list_id: !bench && UUID.test(value) ? value : undefined,
    limit: VIEW_PAGE,
    offset,
  };
}

/** The `vtab` of the URL, `entries` unless it names the PDF. */
export function viewTabOf(value: string | undefined): ViewTab {
  return value === "pdf" ? "pdf" : "entries";
}
