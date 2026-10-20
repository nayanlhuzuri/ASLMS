/**
 * Pure helpers of My calendar (design portal-ui-redesign, decision 8): the month grid from the Monday on or before the
 * 1st to the Sunday on or after the last day (the API's default range, A6), the `?month=` / `?day=` values, and the
 * accessible name of a day from its items. Dates are IST calendar days as `YYYY-MM-DD`; nothing here reads the
 * browser's zone.
 */
import type { MyCalendarItem } from "./api/types";
import { T } from "./messages";
import { parseMonth } from "./workflow";

export const KINDS = ["hearing", "action_due", "confirm"] as const;
export type Kind = (typeof KINDS)[number];

/** The status tone of each kind (decision 11): red hearings, amber action due dates, blue next dates to confirm. */
export const KIND_TONE: Record<Kind, "danger" | "warning" | "info"> = {
  hearing: "danger",
  action_due: "warning",
  confirm: "info",
};

const DAY_MS = 24 * 60 * 60 * 1000;

function utcOf(ymd: string): number {
  const [y, m, d] = ymd.split("-").map(Number) as [number, number, number];
  return Date.UTC(y, m - 1, d);
}

function ymdOf(t: number): string {
  return new Date(t).toISOString().slice(0, 10);
}

/** The weeks of a month's grid, Monday first, each of seven ISO dates, days of the next and previous months included. */
export function gridWeeks(month: string): string[][] {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const first = Date.UTC(y, m - 1, 1);
  const last = Date.UTC(y, m, 0);
  const start = first - ((new Date(first).getUTCDay() + 6) % 7) * DAY_MS;
  const end = last + ((7 - new Date(last).getUTCDay()) % 7) * DAY_MS;
  const weeks: string[][] = [];
  for (let t = start; t <= end; t += 7 * DAY_MS) {
    weeks.push(Array.from({ length: 7 }, (_, i) => ymdOf(t + i * DAY_MS)));
  }
  return weeks;
}

/** The `from` / `to` of `GET /me/calendar` for a month: its grid's first and last days. */
export function gridRange(month: string): { from: string; to: string } {
  const weeks = gridWeeks(month);
  return { from: weeks[0]![0]!, to: weeks[weeks.length - 1]![6]! };
}

/** Saturday or Sunday. */
export function isWeekend(ymd: string): boolean {
  const d = new Date(utcOf(ymd)).getUTCDay();
  return d === 0 || d === 6;
}

/** A `?day=` value as `YYYY-MM-DD`, or null when it is not a real day. */
export function parseDay(value: string | null | undefined): string | null {
  const v = (value ?? "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || !parseMonth(v.slice(0, 7))) return null;
  return ymdOf(utcOf(v)) === v ? v : null;
}

/** Items by date (the API's order kept within a day). */
export function byDate(items: MyCalendarItem[]): Map<string, MyCalendarItem[]> {
  const map = new Map<string, MyCalendarItem[]>();
  for (const item of items) {
    const list = map.get(item.date) ?? [];
    list.push(item);
    map.set(item.date, list);
  }
  return map;
}

/** "22 October: 1 hearing, 1 action due" — the accessible name of a day (colour is never the only signal). */
export function dayName(dayTitle: string, items: MyCalendarItem[]): string {
  const parts: string[] = [];
  for (const kind of KINDS) {
    const n = items.filter((i) => i.kind === kind).length;
    if (n === 0) continue;
    const [one, many] = T.mycal.counts[kind]!;
    parts.push(`${n} ${n === 1 ? one : many}`);
  }
  return T.mycal.dayName(dayTitle, parts);
}
