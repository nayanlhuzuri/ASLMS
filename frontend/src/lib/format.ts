/**
 * Dates in IST (`Asia/Kolkata`) whatever the browser's zone, written `25 Sep 2026`; numbers in the Indian grouping
 * (`1,28,400`). Month names are fixed here so every browser shows the same text.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ZONE = "Asia/Kolkata";

interface Parts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const FORMAT = new Intl.DateTimeFormat("en-GB", {
  timeZone: ZONE,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function istParts(date: Date): Parts {
  const parts = FORMAT.formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute") };
}

function toDate(value: string | Date): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  // a plain date (YYYY-MM-DD) is a calendar day, not an instant
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T12:00:00+05:30`);
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const p = istParts(d);
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}`;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const p = istParts(d);
  const hh = String(p.hour).padStart(2, "0");
  const mm = String(p.minute).padStart(2, "0");
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}, ${hh}:${mm}`;
}

/** The IST time of an instant, `14:34` (no date). */
export function formatTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = toDate(value);
  if (!d) return String(value);
  const p = istParts(d);
  return `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
}

/** 128400 → "1,28,400"; negative numbers and decimals keep their sign and fraction. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
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

/**
 * The badge of a hearing date (design portal-cases, decision 10), from IST dates as the hearing calendar: "critical"
 * when the hearing (at the 10:30 sitting) is today or later and at most 48 hours away, "week" when it falls within
 * the next 7 days, else null. The dashboard keeps using the API's own `critical`.
 */
export function hearingBadge(date: string | null | undefined, now: Date = new Date()): "critical" | "week" | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const today = istDay(now);
  if (date < today) return null;
  const sitting = new Date(`${date}T10:30:00+05:30`).getTime();
  if (sitting - now.getTime() <= 48 * 3600 * 1000) return "critical";
  if (date <= addDays(today, 7)) return "week";
  return null;
}
