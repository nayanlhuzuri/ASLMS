/**
 * The case's one next hearing in test fixtures (design next-date-direct, decision 11): a court date as the server
 * gives it (`NextHearingOut`, basis `court`), and the case-detail form derived from `status.next_hearing_date` when a
 * test sets only the court's date.
 */
import type { CaseDetail } from "@/lib/api/types";
import type { NextHearing } from "@/lib/hearingDate";

export function courtNext(date: string | null | undefined, extra: Partial<NextHearing> = {}): NextHearing | null {
  if (!date) return null;
  return { date, basis: "court", approximate: false, basis_words: null, order: null, rule: null, differs: null, ...extra };
}

/** A next hearing read from an order (exact, or around for a period). */
export function orderNext(date: string, extra: Partial<NextHearing> = {}): NextHearing {
  return {
    date,
    basis: "order",
    approximate: false,
    basis_words: null,
    order: { id: "o-1", order_no: "4", order_date: "2026-10-12", document_id: "d-1" },
    rule: "list_on_date",
    differs: null,
    ...extra,
  };
}

/** A case detail whose `next_hearing` follows its court date unless the test gives one. */
export function withNextHearing<T extends Partial<CaseDetail>>(c: T, extra: Partial<CaseDetail> = {}): T {
  if ("next_hearing" in extra) return c;
  const status = (c as Partial<CaseDetail>).status;
  return { ...c, next_hearing: courtNext(status?.next_hearing_date ?? null) };
}
