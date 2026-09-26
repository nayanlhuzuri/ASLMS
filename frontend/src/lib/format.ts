/** Dates as DD Mon YYYY (Indian English), times in IST. */

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
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAYS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

interface Parts {
  y: number;
  m: number; // 1-12
  d: number;
  hh: number;
  mm: number;
}

const istFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function istParts(date: Date): Parts {
  const p: Record<string, string> = {};
  for (const part of istFormatter.formatToParts(date)) p[part.type] = part.value;
  return { y: Number(p.year), m: Number(p.month), d: Number(p.day), hh: Number(p.hour), mm: Number(p.minute) };
}

function parts(value: string | Date): Parts | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : istParts(value);
  const m = DATE_ONLY.exec(value);
  if (m) return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]), hh: 0, mm: 0 };
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? null : istParts(dt);
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 26 Sep 2026 */
export function fmtDate(value: string | Date | null | undefined, fallback = "-"): string {
  if (!value) return fallback;
  const p = parts(value);
  return p ? `${pad(p.d)} ${MONTHS[p.m - 1]} ${p.y}` : fallback;
}

/** 26 Sep 2026, 14:05 IST */
export function fmtDateTime(value: string | Date | null | undefined, fallback = "-"): string {
  if (!value) return fallback;
  const p = parts(value);
  return p ? `${pad(p.d)} ${MONTHS[p.m - 1]} ${p.y}, ${pad(p.hh)}:${pad(p.mm)} IST` : fallback;
}

/** 26 Sep */
export function fmtDayMonth(value: string): string {
  const p = parts(value);
  return p ? `${pad(p.d)} ${MONTHS[p.m - 1]}` : value;
}

/** Mon */
export function weekday(value: string): string {
  const p = parts(value);
  if (!p) return "";
  return WEEKDAYS[new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay()];
}

/** Friday, 25 September 2026 */
export function fmtLongDate(value: string): string {
  const p = parts(value);
  if (!p) return value;
  const wd = WEEKDAYS_LONG[new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay()];
  return `${wd}, ${p.d} ${MONTHS_LONG[p.m - 1]} ${p.y}`;
}

export function monthTitle(year: number, month0: number): string {
  return `${MONTHS_LONG[month0]} ${year}`;
}

/** Today's date in IST as YYYY-MM-DD. */
export function todayIST(): string {
  const p = istParts(new Date());
  return `${p.y}-${pad(p.m)}-${pad(p.d)}`;
}

export function isoDate(y: number, m0: number, d: number): string {
  const dt = new Date(Date.UTC(y, m0, d));
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}

export function addDays(iso: string, n: number): string {
  const m = DATE_ONLY.exec(iso);
  if (!m) return iso;
  return isoDate(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + n);
}

/** Whole days from today (IST) to a date; negative when past. */
export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const a = DATE_ONLY.exec(todayIST());
  const b = DATE_ONLY.exec(iso.slice(0, 10));
  if (!a || !b) return null;
  const ta = Date.UTC(Number(a[1]), Number(a[2]) - 1, Number(a[3]));
  const tb = Date.UTC(Number(b[1]), Number(b[2]) - 1, Number(b[3]));
  return Math.round((tb - ta) / 86_400_000);
}

export type HearingBand = "critical" | "week" | null;

/** Within 48 hours is critical; within seven days is "this week". */
export function hearingBand(iso: string | null | undefined): HearingBand {
  const d = daysUntil(iso);
  if (d === null || d < 0) return null;
  if (d <= 2) return "critical";
  if (d <= 7) return "week";
  return null;
}

const numberFormat = new Intl.NumberFormat("en-IN");

export function fmtNumber(n: number | null | undefined): string {
  return n === null || n === undefined ? "-" : numberFormat.format(n);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function fmtScore(n: number): string {
  return n.toFixed(2);
}

export function fmtPercent(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

/** "Petitioner vs. Respondent" for a case card. */
export function parties(petitioner: string | null | undefined, respondent: string | null | undefined): string {
  const p = petitioner?.trim();
  const r = respondent?.trim();
  if (p && r) return `${p} vs. ${r}`;
  return p || r || "Parties not yet known";
}

/** A readable label from a snake_case code: "affidavit_in_opposition" -> "Affidavit in opposition". */
export function humanize(code: string | null | undefined): string {
  if (!code) return "-";
  const s = code.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
