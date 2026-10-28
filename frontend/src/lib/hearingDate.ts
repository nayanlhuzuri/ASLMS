/**
 * The band of a next hearing date (design next-hearing-highlight, decisions 2, 3, 5 and 6): one pure rule in whole IST
 * days, read by the kit's `HearingDate` wherever a case's next hearing is shown. It reads the IST day only through
 * `istDay`, never the browser's zone and never an hour (ASLMS does not hold the hearing time).
 * - `hearingBand`: today, tomorrow, week (2 to 7 days ahead), later, passed, none or disposed; first match wins.
 * - `hearingWords`: the word shown before the date, or null (the later band in the small size reads the date alone).
 * - `hearingTone`: the look of a band, strong / soft / plain / warning / muted.
 * The bands are fixed, not settings: the alert engine's 48-hour severity and the dashboard's KPI stay server counts.
 *
 * Design next-date-direct, decisions 5 and 8: the case's one next hearing (`NextHearingOut`, made on the server) maps to
 * the badge through `nextHearingProps`; a period, qualified or returnable date read from an order is `around` ("Around"
 * first, in the band's normal fill); `basisLine`, `aroundSentence` and `differsSentence` give the muted lines in words.
 */
import type { NextHearingOut } from "./api/types";
import { daysBetween, formatDate, isCalendarDay, istDay } from "./format";
import { T } from "./messages";

/** The case's one next hearing as the API gives it (list or detail form). */
export type NextHearing = NextHearingOut & {
  phrase?: string | null;
  court_date?: string | null;
  reported_at?: string | null;
};

/** The soft band runs 2 to this many whole IST days ahead (the calendar's "Next 7 Days" window after tomorrow). */
export const HEARING_SOON_DAYS = 7;

export type HearingBand = "today" | "tomorrow" | "week" | "later" | "passed" | "none" | "disposed";
export type HearingKind = "firm" | "suggested" | "around";
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
  if (kind === "around") return word ? `${b.around} · ${word}` : b.around;
  return word;
}

/** The badge's date and kind from the one next hearing (null: no date yet). */
export function nextHearingProps(next: NextHearing | null | undefined): { date: string | null; kind: HearingKind } {
  if (!next) return { date: null, kind: "firm" };
  return { date: next.date, kind: next.basis === "around" ? "around" : "firm" };
}

/** The owner's form of an around date: "Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)"; null otherwise. */
export function aroundSentence(next: NextHearing | null | undefined): string | null {
  if (!next || next.basis !== "around") return null;
  const od = next.order?.order_date ? formatDate(next.order.order_date) : null;
  return T.hearing.aroundSentence(formatDate(next.date), next.basis_words ?? null, od);
}

/**
 * The one muted line under a medium badge: "From the court's records", "Given in the order of 12 Oct 2026", "From the
 * order of 12 Oct 2026", "Entered by hand; the court has given no date" (an around date says its own sentence).
 */
export function basisLine(next: NextHearing | null | undefined): string | null {
  if (!next) return null;
  const od = next.order?.order_date ? formatDate(next.order.order_date) : null;
  switch (next.basis) {
    case "court":
      return T.hearing.basis.court;
    case "order":
      return od ? T.hearing.basis.order(od) : null;
    case "confirmed":
      return od ? T.hearing.basis.confirmed(od) : null;
    case "manual":
      // a date entered against an order is the correction of a misread reading
      return od ? T.hearing.basis.corrected(od) : T.hearing.basis.manual;
    case "around":
      return aroundSentence(next);
    default:
      return null;
  }
}

/**
 * Decision 5: "The order of 12 Oct 2026 gives 20 Nov 2026; the court's record gives 25 Nov 2026. The court's record is
 * used." Null when nothing differs.
 */
export function differsSentence(next: NextHearing | null | undefined): string | null {
  if (!next?.differs) return null;
  const od = next.differs.order?.order_date;
  return T.hearing.differsSentence(od ? formatDate(od) : "—", formatDate(next.differs.date), formatDate(next.date));
}

/** Decision 4: the look of each band. */
export function hearingTone(band: HearingBand): HearingTone {
  if (band === "today" || band === "tomorrow") return "strong";
  if (band === "week") return "soft";
  if (band === "later") return "plain";
  if (band === "passed") return "warning";
  return "muted";
}
