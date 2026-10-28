/**
 * Sorting in the browser with the server's rules (design list-search, decisions 27-29, 35 and 37): one comparator
 * per type, blanks last in both directions, case numbers by type, then number, then year. `sortRows` is stable, so
 * equal values keep the API's order. The direction words name each direction in Title Case.
 */
import { T } from "./messages";

export type SortType = "text" | "number" | "date" | "caseNo";
export type SortDir = "asc" | "desc";
export type Sortable = string | number | null | undefined;

export interface SortState {
  key: string;
  dir: SortDir;
}

const collator = new Intl.Collator("en-IN", { sensitivity: "base", numeric: true });

function blank(v: Sortable): boolean {
  return v === null || v === undefined || v === "";
}

/** Text ignoring case and accents, numbers inside text in natural order. */
export function compareText(a: string, b: string): number {
  return collator.compare(a, b);
}

export function compareNumber(a: number, b: number): number {
  return a - b;
}

/** ISO dates or times compared as dates. */
export function compareDate(a: string, b: string): number {
  const x = Date.parse(a);
  const y = Date.parse(b);
  if (Number.isNaN(x) || Number.isNaN(y)) return compareText(a, b);
  return x - y;
}

/** The case search's number pattern (`case_filters.NUMBER_RE`): `<type> <no>/<year>` or `<type>/<no>/<year>`. */
const NUMBER_RE = /^([A-Z][A-Z().\-\s]*?)\s*[/\s]\s*(\d{1,7})\s*\/\s*(\d{4})$/;

export interface CaseNumber {
  type: string;
  no: number;
  year: number;
}

export function parseCaseNumber(text: string | null | undefined): CaseNumber | null {
  const m = NUMBER_RE.exec((text ?? "").trim().toUpperCase());
  if (!m) return null;
  return { type: (m[1] ?? "").replace(/\s+/g, ""), no: Number(m[2]), year: Number(m[3]) };
}

/** Type (compact, upper case), then number, then year; text that does not parse after parsed numbers. */
export function compareCaseNumbers(a: string, b: string): number {
  const x = parseCaseNumber(a);
  const y = parseCaseNumber(b);
  if (x && y) {
    if (x.type !== y.type) return x.type < y.type ? -1 : 1;
    return x.no - y.no || x.year - y.year;
  }
  if (x) return -1;
  if (y) return 1;
  return compareText(a, b);
}

function compareTyped(type: SortType, a: string | number, b: string | number): number {
  if (type === "number") return compareNumber(Number(a), Number(b));
  if (type === "date") return compareDate(String(a), String(b));
  if (type === "caseNo") return compareCaseNumbers(String(a), String(b));
  return compareText(String(a), String(b));
}

/** Compares two values in a direction with blanks last in both directions. */
export function compareValues(type: SortType, a: Sortable, b: Sortable, dir: SortDir): number {
  const ba = blank(a);
  const bb = blank(b);
  if (ba || bb) return ba === bb ? 0 : ba ? 1 : -1;
  const c = compareTyped(type, a as string | number, b as string | number);
  return dir === "asc" ? c : -c;
}

/** A stable sort of `rows` by `value` (a new array). */
export function sortRows<Row>(rows: readonly Row[], value: (row: Row) => Sortable, type: SortType, dir: SortDir): Row[] {
  return rows
    .map((row, i) => ({ row, i, v: value(row) }))
    .sort((p, q) => compareValues(type, p.v, q.v, dir) || p.i - q.i)
    .map((x) => x.row);
}

/** The first direction of a click (decision 27): ascending for text and case numbers, descending for numbers and past
 * dates; a column may set its own (dates ahead start ascending). */
export function firstDirOf(type: SortType, firstDir?: SortDir): SortDir {
  if (firstDir) return firstDir;
  return type === "number" || type === "date" ? "desc" : "asc";
}

/** Decision 29: the words of each direction, `[asc, desc]`. */
export function dirWords(type: SortType, firstDir?: SortDir, labels?: readonly [string, string]): [string, string] {
  const d = T.list.dirLabels;
  if (labels) return [labels[0], labels[1]];
  if (type === "text") return [d.textAsc, d.textDesc];
  if (type === "number") return [d.numberAsc, d.numberDesc];
  if (type === "caseNo") return [d.caseNoAsc, d.caseNoDesc];
  // a date ahead (Next Hearing, Due Date) starts with the earliest; a past date with the newest
  return firstDirOf(type, firstDir) === "asc" ? [d.aheadAsc, d.aheadDesc] : [d.pastAsc, d.pastDesc];
}

export function dirWord(type: SortType, dir: SortDir, firstDir?: SortDir, labels?: readonly [string, string]): string {
  const [asc, desc] = dirWords(type, firstDir, labels);
  return dir === "asc" ? asc : desc;
}

/** The three-click cycle (decision 27): first direction, the other direction, then the list's default (null). */
export function nextSort(current: SortState | null, key: string, first: SortDir): SortState | null {
  if (!current || current.key !== key) return { key, dir: first };
  if (current.dir === first) return { key, dir: first === "asc" ? "desc" : "asc" };
  return null;
}
