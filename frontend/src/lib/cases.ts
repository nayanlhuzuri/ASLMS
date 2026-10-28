/**
 * Plain case words shared by the case page, its rail, the remarks history and the Cases list (design
 * case-workspace-admin, decisions 11, 13 and 19):
 * - `withText`: who a case is with, "<designation>, <office>" with "(you)" for the caller; the person's name only when
 *   the membership has no designation, and always as the title attribute;
 * - `leadBadge`: the lead badge of the custody lists, one pure rule per list (first match wins); Working on reads the
 *   row's custody brief only when the case is with the caller (design case-inbox-merge, decision 8).
 * The whole-day countdown to a hearing is `lib/hearingDate.ts` (design next-hearing-highlight, decision 2).
 */
import type { CustodyCard, CustodyLeg, HeldItem, MyCase, SentItem } from "./api/types";
import { addDays, daysBetween, istDay } from "./format";
import { T } from "./messages";

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

/** Who sent the case to the current holder (the current leg's sender). */
export function cardSender(card: CustodyCard | null | undefined): WithParty | null {
  const by = card?.sent_by;
  if (!by || (!by.name && !by.designation && !by.office_code)) return null;
  return { designation: by.designation, office: by.office_code, name: by.name };
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

/** The person who wrote a leg (the sender, recaller or ownership actor). */
export function legActor(leg: CustodyLeg): WithParty | null {
  if (!leg.actor_name && !leg.actor_designation && !leg.actor_office_code) return null;
  return { designation: leg.actor_designation, office: leg.actor_office_code, name: leg.actor_name };
}

export type CasesTab = "with-me" | "pending" | "sent" | "working";

export interface LeadBadge {
  label: string;
  tone?: "danger" | "warning" | "info";
}

/** The window of "Due soon" on Sent by me, whose legs carry no server flag: the server's default (decision 19). */
export const SENT_DUE_SOON_DAYS = 2;

const NEW_MS = 48 * 3600 * 1000;

function isNew(since: string | null | undefined, now: Date): boolean {
  const t = since ? Date.parse(since) : NaN;
  return Number.isFinite(t) && now.getTime() - t <= NEW_MS && now.getTime() >= t;
}

/** Decision 19's table, first match wins; null leaves the 96 px column empty. */
export function leadBadge(row: HeldItem | SentItem | MyCase, tab: CasesTab, now: Date = new Date()): LeadBadge | null {
  if (tab === "working") {
    // design case-inbox-merge, decision 8: only a case with me carries a badge
    const brief = (row as MyCase).custody;
    if (!brief?.with_me) return null;
    if (brief.overdue) return { label: T.cases.lead.overdue, tone: "danger" };
    if (brief.due_soon) return { label: T.cases.lead.dueSoon, tone: "warning" };
    if (isNew(brief.since, now)) return { label: T.cases.lead.new, tone: "info" };
    return null;
  }
  if (tab === "sent") {
    const item = row as SentItem;
    if (item.current !== true) return null;
    const due = item.leg.due_date;
    const today = istDay(now);
    if (due && due < today) return { label: T.cases.lead.overdue, tone: "danger" };
    if (due && due <= addDays(today, SENT_DUE_SOON_DAYS)) return { label: T.cases.lead.dueSoon, tone: "warning" };
    return { label: T.cases.lead.waiting };
  }
  const card = (row as HeldItem).card;
  if (card?.overdue) return { label: T.cases.lead.overdue, tone: "danger" };
  if (card?.due_soon) return { label: T.cases.lead.dueSoon, tone: "warning" };
  if (tab === "with-me") return isNew(card?.since, now) ? { label: T.cases.lead.new, tone: "info" } : null;
  return { label: T.cases.lead.waiting };
}

/** Whole IST days from today to a due date: positive = days left, negative = days overdue. */
export function daysUntil(date: string, now: Date = new Date()): number {
  return daysBetween(istDay(now), date);
}
