/**
 * Plain case words shared by the case page, its rail, the remarks history and the Cases list (design
 * case-workspace-admin, decisions 11, 13 and 19):
 * - `withText`: who a case is with, "<designation>, <office>" with "(you)" for the caller; the person's name only when
 *   the membership has no designation, and always as the title attribute;
 * - `isNewSince` and `sentDue`: the "New" mark of With Me and the Due line of Sent by Me (design
 *   portal-screen-fixes-work, decisions 3 and 5; the lead badge column is gone).
 * - `statusTone`: the tone of the case status badge, shared by the case header and Search's Status cell (design
 *   portal-screen-fixes-oversight, decision 2).
 * The whole-day countdown to a hearing is `lib/hearingDate.ts` (design next-hearing-highlight, decision 2).
 */
import type { CustodyCard, CustodyLeg, OfficeNameMap, SentItem } from "./api/types";
import { addDays, daysBetween, istDay } from "./format";
import { T } from "./messages";
import { officeName } from "./officeNames";

/**
 * The case status badge's tone (design portal-ui-redesign, decision 10.15): green means done (disposed); pending and
 * unknown are neutral, amber is kept for due soon.
 */
export function statusTone(status: string | null | undefined): "success" | undefined {
  return status === "disposed" ? "success" : undefined;
}

/** Who a case is with, or who sent it: the parts `withText` reads. */
export interface WithParty {
  designation?: string | null;
  office?: string | null;
  name?: string | null;
  userId?: string | null;
}

export interface WithLabel {
  text: string;
  /** The person's full name, for the title attribute. */
  title?: string;
}

/** Decision 13: "<designation>, <office>", "(you)" for the caller; the name only without a designation. */
export function withText(p: WithParty | null | undefined, meId?: string | null): WithLabel {
  if (!p) return { text: "—" };
  const who = p.designation?.trim() || p.name?.trim() || "";
  const office = p.office?.trim() || "";
  const base = [who, office].filter(Boolean).join(", ") || "—";
  const you = !!meId && !!p.userId && p.userId === meId;
  return { text: you ? T.cases.you(base) : base, title: p.name?.trim() || undefined };
}

/** The holder of a custody card. */
export function cardHolder(card: CustodyCard | null | undefined): WithParty | null {
  if (!card) return null;
  return {
    designation: card.holder_user?.designation ?? null,
    office: card.holder_office?.name ?? card.holder_office?.code ?? null,
    name: card.holder_user?.full_name ?? null,
    userId: card.holder_user?.id ?? null,
  };
}

/** Who sent the case to the current holder (the current leg's sender), the office by name (design portal-names-and-labels). */
export function cardSender(card: CustodyCard | null | undefined, names?: OfficeNameMap): WithParty | null {
  const by = card?.sent_by;
  if (!by || (!by.name && !by.designation && !by.office_code)) return null;
  return { designation: by.designation, office: by.office_code ? officeName(by.office_code, names) : null, name: by.name };
}

/** The holder a leg names. */
export function legHolder(leg: CustodyLeg): WithParty {
  return {
    designation: leg.holder_designation,
    office: leg.holder_office.name || leg.holder_office.code,
    name: leg.holder_user?.full_name ?? null,
    userId: leg.holder_user?.id ?? null,
  };
}

/** The person who wrote a leg (the sender, recaller or ownership actor), the office by name. */
export function legActor(leg: CustodyLeg, names?: OfficeNameMap): WithParty | null {
  if (!leg.actor_name && !leg.actor_designation && !leg.actor_office_code) return null;
  return {
    designation: leg.actor_designation,
    office: leg.actor_office_code ? officeName(leg.actor_office_code, names) : null,
    name: leg.actor_name,
  };
}

/** The window of "Due soon" on Sent by me, whose legs carry no server flag: the server's default (decision 19). */
export const SENT_DUE_SOON_DAYS = 2;

const NEW_MS = 48 * 3600 * 1000;

/** Received in the last 48 hours: With Me's "New" mark (design portal-screen-fixes-work, decision 3). */
export function isNewSince(since: string | null | undefined, now: Date = new Date()): boolean {
  const t = since ? Date.parse(since) : NaN;
  return Number.isFinite(t) && now.getTime() - t <= NEW_MS && now.getTime() >= t;
}

/**
 * The due state of a Sent by Me leg (design portal-screen-fixes-work, decision 5), whose legs carry no server flag:
 * overdue when the leg is still the case's current one and its date is before today in IST, counted in whole days;
 * due soon within `SENT_DUE_SOON_DAYS`; a leg that has moved on shows its date only.
 */
export function sentDue(
  item: Pick<SentItem, "current"> & { leg: Pick<CustodyLeg, "due_date"> },
  now: Date = new Date(),
): { date: string | null; overdue: boolean; overdueDays: number; dueSoon: boolean } {
  const date = item.leg.due_date ?? null;
  if (!date || item.current !== true) return { date, overdue: false, overdueDays: 0, dueSoon: false };
  const today = istDay(now);
  if (date < today) return { date, overdue: true, overdueDays: -daysUntil(date, now), dueSoon: false };
  return { date, overdue: false, overdueDays: 0, dueSoon: date <= addDays(today, SENT_DUE_SOON_DAYS) };
}

/** Whole IST days from today to a due date: positive = days left, negative = days overdue. */
export function daysUntil(date: string, now: Date = new Date()): number {
  return daysBetween(istDay(now), date);
}
