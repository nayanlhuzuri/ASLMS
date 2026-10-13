/**
 * Pure helpers of the case-page workflow (design portal-workflow, decisions 5, 13): today in IST, the due-date
 * bounds offered as a hint (the API decides, `bad_due_date`), and the checks made on a file before it is sent
 * (the API still decides by the file's bytes).
 */

const ZONE = "Asia/Kolkata";
const DAY_MS = 24 * 60 * 60 * 1000;
export const MAX_DUE_DAYS = 365;

const YMD = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit" });

/** The calendar day in IST of an instant, `YYYY-MM-DD`. */
export function todayIst(now: Date = new Date()): string {
  return YMD.format(now);
}

function addDays(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map(Number) as [number, number, number];
  const t = Date.UTC(y, m - 1, d) + days * DAY_MS;
  return new Date(t).toISOString().slice(0, 10);
}

/** The due-date input's `min` and `max`: today (IST) to today + 365 days. */
export function dueDateBounds(now: Date = new Date()): { min: string; max: string } {
  const min = todayIst(now);
  return { min, max: addDays(min, MAX_DUE_DAYS) };
}

/** The earliest document date an upload may carry (documents-uploads). */
export const EARLIEST_DOC_DATE = "1950-01-01";

export interface UploadLimits {
  max_bytes: number;
  extensions: string[];
}

export type FileProblem = { code: "type_not_allowed"; extensions: string[] } | { code: "too_large"; maxBytes: number } | { code: "empty" };

function extensionOf(name: string): string | null {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? "";
  const i = base.lastIndexOf(".");
  return i > 0 && i < base.length - 1 ? base.slice(i + 1).toLowerCase() : null;
}

/** The pre-check of a chosen file against the server's limits (`GET /documents/types` → `upload`); null when fine. */
export function checkFile(file: Pick<File, "name" | "size">, upload: UploadLimits): FileProblem | null {
  const ext = extensionOf(file.name);
  if (!ext || !upload.extensions.map((e) => e.toLowerCase()).includes(ext)) {
    return { code: "type_not_allowed", extensions: upload.extensions };
  }
  if (file.size > upload.max_bytes) return { code: "too_large", maxBytes: upload.max_bytes };
  if (file.size === 0) return { code: "empty" };
  return null;
}

/** The `accept` attribute of a file input from the permitted extensions. */
export function acceptOf(upload: UploadLimits | undefined): string | undefined {
  return upload ? upload.extensions.map((e) => `.${e}`).join(",") : undefined;
}

/** A size limit for messages: `20 MB`, `1.5 MB`, `300 KB`, `50 bytes`. */
export function megabytes(bytes: number): string {
  const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  if (bytes >= 1024 * 1024) return `${trim(bytes / (1024 * 1024))} MB`;
  if (bytes >= 1024) return `${trim(bytes / 1024)} KB`;
  return `${bytes} bytes`;
}

// ------------------------------------------------------------------------------------------------ hearing calendar

const MONTH_RE = /^(\d{4})-(\d{2})$/;

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** A `?month=` value as `YYYY-MM`, or null when it is not a real month (design portal-files-alerts, decision 10). */
export function parseMonth(value: string | null | undefined): string | null {
  const m = MONTH_RE.exec((value ?? "").trim());
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (year < 1950 || year > 2200 || month < 1 || month > 12) return null;
  return `${m[1]}-${m[2]}`;
}

/** The first and last day of a month (`YYYY-MM`), as ISO dates: the `from` / `to` of `GET /calendar`. */
export function monthRange(month: string): { from: string; to: string } {
  const [y, m] = month.split("-").map(Number) as [number, number];
  return { from: `${month}-01`, to: `${month}-${pad2(daysIn(y, m))}` };
}

/** The month `delta` months away, `YYYY-MM`. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${pad2((index % 12) + 1)}`;
}

/** The month of an ISO date, `YYYY-MM`. */
export function monthOf(ymd: string): string {
  return ymd.slice(0, 7);
}

/** The weeks of a month, Monday first, each of seven ISO dates; `null` for the days outside the month. */
export function monthGrid(month: string): (string | null)[][] {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const first = new Date(Date.UTC(y, m - 1, 1)).getUTCDay(); // 0 = Sunday
  const lead = (first + 6) % 7; // days before the 1st in a Monday-first week
  const cells: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= daysIn(y, m); d++) cells.push(`${month}-${pad2(d)}`);
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}
