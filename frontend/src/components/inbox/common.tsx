"use client";

/**
 * Shared pieces of the inbox, search and case screens (design portal-cases, decisions 1 and 5): filters kept in the
 * query string (a list can be bookmarked and the back button restores it), the parties line, the latest-listing line
 * and the next-hearing line of a case summary.
 */
import { usePathname, useRouter } from "next/navigation";

import type { CaseSummary } from "@/lib/api/types";
import { queryString, type Params } from "@/lib/params";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";

/** Writes filters into the current page's query string; any filter change goes back to the first page. */
export function useFilters(params: Params) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  return (updates: Params, { keepOffset = false }: { keepOffset?: boolean } = {}) => {
    const next: Params = { ...params, ...updates };
    if (!keepOffset && !("offset" in updates)) delete next.offset;
    router.replace(pathname + queryString(next));
  };
}

export function PartiesLine({ c }: { c: Pick<CaseSummary, "petitioner_summary" | "respondent_summary"> }) {
  if (!c.petitioner_summary && !c.respondent_summary) return null;
  return (
    <div>
      {c.petitioner_summary ?? "—"} <span className="muted">{T.vs}</span> {c.respondent_summary ?? "—"}
    </div>
  );
}

export function ListingLine({ c }: { c: Pick<CaseSummary, "last_listing" | "next_hearing_date"> }) {
  const parts: string[] = [];
  if (c.last_listing) {
    parts.push(T.inbox.listing(formatDate(c.last_listing.list_date), c.last_listing.court_no, c.last_listing.sr_no));
  }
  if (c.next_hearing_date) parts.push(T.inbox.nextHearing(formatDate(c.next_hearing_date)));
  if (parts.length === 0) return null;
  return <div className="muted">{parts.join(" · ")}</div>;
}
