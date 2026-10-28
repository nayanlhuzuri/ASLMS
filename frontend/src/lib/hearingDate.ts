/**
 * The band of a next hearing date (design next-hearing-highlight, decisions 2, 3, 5 and 6): one pure rule in whole IST
 * days, read by the kit's `HearingDate` wherever a case's next hearing is shown. It reads the IST day only through
 * `istDay`, never the browser's zone and never an hour (ASLMS does not hold the hearing time).
 * - `hearingBand`: today, tomorrow, week (2 to 7 days ahead), later, passed, none or disposed; first match wins.
 * - `hearingWords`: the word shown before the date, or null (the later band in the small size reads the date alone).
 * - `hearingTone`: the look of a band, strong / soft / plain / warning / muted.
 * The bands are fixed, not settings: the alert engine's 48-hour severity and the dashboard's KPI stay server counts.
 */
import { daysBetween, isCalendarDay, istDay } from "./format";
import { T } from "./messages";

/** The soft band runs 2 to this many whole IST days ahead (the calendar's "Next 7 Days" window after tomorrow). */
export const HEARING_SOON_DAYS = 7;

export type HearingBand = "today" | "tomorrow" | "week" | "later" | "passed" | "none" | "disposed";
export type HearingKind = "firm" | "suggested";
export type HearingSize = "sm" | "md";
export type HearingTone = "strong" | "soft" | "plain" | "warning" | "muted";

/** Decision 2: the band and the whole IST days from today to the date (null without a date). */
export function hearingBand(
  date: string | null | undefined,
  { status, now = new Date() }: { status?: string | null; now?: Date } = {},
): { band: HearingBand; days: number | null } {
  // an impossible day ("2026-02-30") is no date, not a rolled-over one
  const days = isCalendarDay(date) ? daysBetween(istDay(now), date) : null;
  if (status === "disposed") return { band: "disposed", days };
  if (days === null) return { band: "none", days: null };
  if (days < 0) return { band: "passed", days };
  if (days === 0) return { band: "today", days };
  if (days === 1) return { band: "tomorrow", days };
  if (days <= HEARING_SOON_DAYS) return { band: "week", days };
  return { band: "later", days };
}

/**
 * Decisions 5 and 6: the word before the date. "Suggested" comes first for a date read from an order and not yet
 * confirmed; the later band has a word ("In 20 Days") only in the medium size, so a list reads the date alone.
 */
export function hearingWords(
  band: HearingBand,
  days: number | null,
  { kind = "firm", size = "sm" }: { kind?: HearingKind; size?: HearingSize } = {},
): string | null {
  const b = T.hearing.badges;
  let word: string | null;
  if (band === "today") word = b.today;
  else if (band === "tomorrow") word = b.tomorrow;
  else if (band === "week") word = b.inDays(days ?? 0);
  else if (band === "later") word = size === "md" ? b.inDays(days ?? 0) : null;
  else if (band === "passed") word = b.passed;
  else if (band === "disposed") return b.disposed;
  else return b.none;
  if (kind === "suggested") return word ? `${b.suggested} · ${word}` : b.suggested;
  return word;
}

/** Decision 4: the look of each band. */
export function hearingTone(band: HearingBand): HearingTone {
  if (band === "today" || band === "tomorrow") return "strong";
  if (band === "week") return "soft";
  if (band === "later") return "plain";
  if (band === "passed") return "warning";
  return "muted";
}
