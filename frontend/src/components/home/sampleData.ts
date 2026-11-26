/**
 * The sample data of the home page's two pictures (design home-page-refinements, decisions 3 and 4, by the owner's
 * leave): static, never fetched, and impossible to mistake for a held case. Case numbers keep the court's format with
 * the number masked (`WP(C)/XXXX/2026`), no CNR is given, parties are invented generic names or role words beside
 * "State of Assam & Ors.", no department, officer or judge is named (the From column shows a designation only), and
 * every date lies in one fixed sample month counted from `SAMPLE_NOW`, so the picture never goes out of date. The labels
 * drawn around the data are the portal's own messages.
 */
import type { DueState } from "@/components/inbox/rows";
import { formatDate } from "@/lib/format";

/** The sample "today" every date of the pictures is counted from (a Monday in the fixed sample month). */
export const SAMPLE_NOW = new Date("2027-01-11T10:30:00+05:30");

export interface SampleRow {
  key: string;
  caseNo: string;
  petitioner: string;
  respondent: string;
  /** The next hearing (`HearingDate`); null reads No Date Yet. */
  next: string | null;
  status: "pending" | "disposed";
  action: string | null;
  due: DueState;
  /** A designation only: no officer is named. */
  from: string;
  /** Marks under the case number, as the inbox draws them (`New`, `Ready to Close`). */
  isNew?: boolean;
}

const noDue: DueState = { date: null, overdue: false, overdueDays: 0, dueSoon: false };

/** The Case Inbox picture's six rows: Tomorrow in red, two within a week in amber, a later date, no date, disposed. */
export const SAMPLE_ROWS: SampleRow[] = [
  {
    key: "r1",
    caseNo: "WP(C)/XXXX/2026",
    petitioner: "A. Sample & Ors.",
    respondent: "State of Assam & Ors.",
    next: "2027-01-12",
    status: "pending",
    action: "File Affidavit-in-Opposition",
    due: { date: "2027-01-09", overdue: true, overdueDays: 2, dueSoon: false },
    from: "Deputy Secretary",
    isNew: true,
  },
  {
    key: "r2",
    caseNo: "WA/XXX/2025",
    petitioner: "State of Assam & Ors.",
    respondent: "B. Sample",
    next: "2027-01-15",
    status: "pending",
    action: "Approve Draft Reply",
    due: { date: "2027-01-14", overdue: false, overdueDays: 0, dueSoon: true },
    from: "Under Secretary",
  },
  {
    key: "r3",
    caseNo: "WP(C)/XXXX/2025",
    petitioner: "C. Sample",
    respondent: "State of Assam & Ors.",
    next: "2027-01-17",
    status: "pending",
    action: "Comply With the Order",
    due: { date: "2027-01-20", overdue: false, overdueDays: 0, dueSoon: false },
    from: "Joint Secretary",
  },
  {
    key: "r4",
    caseNo: "CONT.CAS(C)/XXX/2026",
    petitioner: "D. Sample",
    respondent: "State of Assam & Ors.",
    next: "2027-01-28",
    status: "pending",
    action: "Send Compliance Report",
    due: { date: "2027-01-25", overdue: false, overdueDays: 0, dueSoon: false },
    from: "Section Officer",
  },
  {
    key: "r5",
    caseNo: "WP(C)/XXXX/2026",
    petitioner: "F. Sample & Ors.",
    respondent: "State of Assam & Ors.",
    next: null,
    status: "pending",
    action: "Examine and Put Up",
    due: noDue,
    from: "Deputy Secretary",
  },
  {
    key: "r6",
    caseNo: "MC/XXXX/2026",
    petitioner: "State of Assam",
    respondent: "G. Sample",
    next: null,
    status: "disposed",
    action: null,
    due: noDue,
    from: "Under Secretary",
  },
];

/** One source of a sample answer, drawn as the Assistant draws a court source: its kind, title and excerpt. */
export interface SampleSource {
  label: string;
  kind: string;
  title: string;
  passage: string;
}

export type SampleMessage =
  | { who: "q"; text: string }
  /** `text` carries the Assistant's own `[S1]` markers, read by `markers()` as on the Assistant page. */
  | { who: "a"; text: string; sources: SampleSource[] };

const ORDER_DAY = formatDate("2027-01-04");
const NEXT_DAY = formatDate("2027-01-12");

const ORDER_SOURCE: SampleSource = {
  label: "S1",
  kind: "Court Order",
  title: `Order of ${ORDER_DAY}, page 2`,
  passage: "…the State respondents shall file their affidavit-in-opposition within three weeks. List after one week for orders…",
};

const DETAILS_SOURCE: SampleSource = {
  label: "S2",
  kind: "Case Details",
  title: "Case Details",
  passage: `Next hearing ${NEXT_DAY} · Item 14 · WP(C)/XXXX/2026 · For Orders`,
};

/** The Assistant picture's conversation: two questions and two answers about one sample case. */
export const SAMPLE_CHAT: SampleMessage[] = [
  { who: "q", text: "What did the court direct in the last order?" },
  {
    who: "a",
    text: "The court directed the State respondents to file their affidavit-in-opposition within three weeks [S1]. It also directed that the case be listed again after one week for orders [S1].",
    sources: [ORDER_SOURCE],
  },
  { who: "q", text: "When is the case listed next?" },
  {
    who: "a",
    text: `It is listed tomorrow, ${NEXT_DAY}, for orders, as the last order directed [S1]. The case details show it as item 14 on that day's list [S2].`,
    sources: [ORDER_SOURCE, DETAILS_SOURCE],
  },
];
