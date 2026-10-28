/**
 * Dates in IST (`Asia/Kolkata`) whatever the browser's zone, written `25 Sep 2026`; numbers in the Indian grouping
 * (`1,28,400`). Month names are fixed here so every browser shows the same text. Each function takes the locale
 * (design portal-ui-redesign, decision 27): English keeps these fixed texts; any other locale goes through
 * `Intl.DateTimeFormat` / `Intl.NumberFormat` in IST.
 */
import { DEFAULT_LOCALE, localeOf, type LocaleInfo } from "./i18n";

/** A locale code or a locale; omitted, English. */
export type LocaleArg = string | LocaleInfo;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const ZONE = "Asia/Kolkata";

/** The `Intl` locale when the locale is not English, else null (the fixed English texts apply). */
function intlOf(locale?: LocaleArg): string | null {
  const l = localeOf(locale);
  return l.code === DEFAULT_LOCALE ? null : l.intl;
}

function intlDate(value: Date, intl: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(intl, { timeZone: ZONE, ...options }).format(value);
}

interface Parts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

const FORMAT = new Intl.DateTimeFormat("en-GB", {
  timeZone: ZONE,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function istParts(date: Date): Parts {
  const parts = FORMAT.formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute"), second: get("second") };
}

function toDate(value: string | Date): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  // a plain date (YYYY-MM-DD) is a calendar day, not an instant
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T12:00:00+05:30`);
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDate(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { day: "numeric", month: "short", year: "numeric" });
  const p = istParts(d);
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}`;
}

export function formatDateTime(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) {
    return intlDate(d, intl, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  }
  const p = istParts(d);
  const hh = String(p.hour).padStart(2, "0");
  const mm = String(p.minute).padStart(2, "0");
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}, ${hh}:${mm}`;
}

/** An instant in IST to the second, `14 Oct 2026, 14:34:07` (design portal-audit-health, decision 5). */
export function formatDateTimeSeconds(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) {
    return intlDate(d, intl, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
  }
  const p = istParts(d);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}, ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/** The IST time of an instant, `14:34` (no date). */
export function formatTime(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const p = istParts(d);
  return `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
}

/** 128400 → "1,28,400"; negative numbers and decimals keep their sign and fraction. */
export function formatNumber(value: number | null | undefined, locale?: LocaleArg): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const intl = intlOf(locale);
  if (intl) return new Intl.NumberFormat(intl, { maximumFractionDigits: 20 }).format(value);
  const negative = value < 0;
  const [whole = "0", fraction] = Math.abs(value).toString().split(".");
  let grouped = whole;
  if (whole.length > 3) {
    const last3 = whole.slice(-3);
    const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    grouped = `${rest},${last3}`;
  }
  return `${negative ? "-" : ""}${grouped}${fraction ? "." + fraction : ""}`;
}

/** The day and short month of a date in IST, `{ day: "22", month: "Oct" }`, for the `DateChip` (decision 15). */
export function dayMonth(value: string | Date | null | undefined, locale?: LocaleArg): { day: string; month: string } | null {
  if (!value) return null;
  const d = toDate(value);
  if (!d) return null;
  const intl = intlOf(locale);
  if (intl) return { day: intlDate(d, intl, { day: "numeric" }), month: intlDate(d, intl, { month: "short" }) };
  const p = istParts(d);
  return { day: String(p.day), month: MONTHS[p.month - 1]! };
}

/** The weekday of a date in IST, `Tuesday` (the calendar and the greeting). */
export function formatWeekday(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { weekday: "long" });
  const p = istParts(d);
  // the IST calendar day's weekday, counted in UTC so the browser's zone plays no part
  return WEEKDAYS[new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay()]!;
}

/** "Wed, 28 Oct 2026": the short weekday and the date, both in IST (the medium `HearingDate`, design next-hearing-highlight). */
export function weekdayDate(date: string): string {
  return `${formatWeekday(date).slice(0, 3)}, ${formatDate(date)}`;
}

/** The month and year of a date in IST, `October 2026` (the calendar's heading). */
export function formatMonthYear(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { month: "long", year: "numeric" });
  const p = istParts(d);
  return `${MONTHS_LONG[p.month - 1]} ${p.year}`;
}

/** A day with its weekday, `Tuesday, 21 October` (My calendar's agenda heading and day names). */
export function formatDayLong(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { weekday: "long", day: "numeric", month: "long" });
  const p = istParts(d);
  return `${formatWeekday(d)}, ${p.day} ${MONTHS_LONG[p.month - 1]}`;
}

/** A day with its weekday and year, `Sunday, 25 October 2026` (the dashboard's date, design portal-ui-polish-2). */
export function formatDayLongYear(value: string | Date | null | undefined, locale?: LocaleArg): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const intl = intlOf(locale);
  if (intl) return intlDate(d, intl, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const p = istParts(d);
  return `${formatWeekday(d)}, ${p.day} ${MONTHS_LONG[p.month - 1]} ${p.year}`;
}

/** The hour (0-23) of an instant in IST (the dashboard greeting). */
export function istHour(now: Date = new Date()): number {
  return istParts(now).hour;
}

/**
 * True for a real calendar day written `YYYY-MM-DD`: the engine rolls an impossible day over ("2026-02-30" parses as
 * 2 March), so the day must survive the round trip. Counted in UTC, so the browser's zone plays no part.
 */
export function isCalendarDay(value: string | null | undefined): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

/** Whole calendar days from `from` to `to` (both `YYYY-MM-DD`); negative when `to` is earlier. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/** The IST calendar day of an instant as `YYYY-MM-DD`. */
export function istDay(now: Date = new Date()): string {
  const p = istParts(now);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

/** `YYYY-MM-DD` plus `days` calendar days. */
export function addDays(day: string, days: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
