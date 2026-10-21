"use client";

/**
 * The Hearings tab (design portal-cases, decision 10): the hearings (business date, purpose, bench, next date,
 * business text, short order) and, below, the cause-list appearances (date, list type, bench, court, item, section,
 * connected, counsel codes, remarks), each linking to that day's cause list for its bench (design portal-causelist,
 * decision 12). Between them, "Next dates": every next date of the case with the one used for the calendar (design
 * portal-next-dates, decision 10).
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { NextDatesSection } from "@/components/nextdates/CaseNextDate";
import { DataTable, EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import { causelistHref } from "@/lib/causelist";
import type { HearingList, ListingList } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";

export function Hearings({ caseRef }: { caseRef: string }) {
  const [hOffset, setHOffset] = useState(0);
  const [lOffset, setLOffset] = useState(0);
  const base = apiCasePath(caseRef);
  const hearings = useQuery({
    queryKey: [...caseKey(caseRef), "hearings", "page", hOffset],
    queryFn: () => api<HearingList>(`${base}/hearings`, { query: { limit: PAGE, offset: hOffset } }),
  });
  const listings = useQuery({
    queryKey: [...caseKey(caseRef), "listings", "page", lOffset],
    queryFn: () => api<ListingList>(`${base}/listings`, { query: { limit: PAGE, offset: lOffset } }),
  });
  return (
    <div className="stack">
      <section className="stack" aria-label={T.case.hearings}>
        <h2>{T.case.hearings}</h2>
        {hearings.isPending ? <Loading /> : null}
        <ErrorBanner error={hearings.error} onRetry={() => hearings.refetch()} />
        {hearings.data ? (
          hearings.data.items.length === 0 ? (
            <EmptyState>{T.case.noHearings}</EmptyState>
          ) : (
            <>
              <DataTable
                caption={T.case.hearings}
                rows={hearings.data.items.map((h, i) => ({ h, i }))}
                rowKey={(row) => String(row.i)}
                columns={[
                  { key: "date", header: T.case.businessDate, primary: true, cell: ({ h }) => formatDate(h.business_date ?? h.hearing_date) },
                  { key: "purpose", header: T.case.purposeCol, cell: ({ h }) => h.purpose ?? "—" },
                  {
                    key: "bench",
                    header: T.case.bench,
                    cell: ({ h }) => (
                      <>
                        {h.bench_text ?? "—"}
                        {h.judge_designation ? <div className="muted">{h.judge_designation}</div> : null}
                      </>
                    ),
                  },
                  { key: "next", header: T.case.nextDate, cell: ({ h }) => formatDate(h.next_date) },
                  {
                    key: "business",
                    header: T.case.business,
                    cell: ({ h }) => (
                      <>
                        {h.business_text ?? "—"}
                        {h.short_order_text ? (
                          <div className="muted">
                            {T.case.shortOrder}: {h.short_order_text}
                          </div>
                        ) : null}
                      </>
                    ),
                  },
                ]}
              />
              <Pagination offset={hOffset} limit={PAGE} total={hearings.data.total} onChange={setHOffset} />
            </>
          )
        ) : null}
      </section>
      <NextDatesSection caseRef={caseRef} />
      <section className="stack" aria-label={T.case.listings}>
        <h2>{T.case.listings}</h2>
        {listings.isPending ? <Loading /> : null}
        <ErrorBanner error={listings.error} onRetry={() => listings.refetch()} />
        {listings.data ? (
          listings.data.items.length === 0 ? (
            <EmptyState>{T.inbox.empty}</EmptyState>
          ) : (
            <>
              <DataTable
                caption={T.case.listings}
                rows={listings.data.items.map((l, i) => ({ l, i }))}
                rowKey={(row) => String(row.i)}
                columns={[
                  {
                    key: "date",
                    header: T.case.listDate,
                    primary: true,
                    cell: ({ l }) => (
                      <>
                        {formatDate(l.list_date)}
                        <div>
                          <Link href={causelistHref(l.list_date, l.bench_id)}>{T.causelist.openCauselist}</Link>
                        </div>
                      </>
                    ),
                  },
                  { key: "type", header: T.case.listType, cell: ({ l }) => l.list_type },
                  { key: "bench", header: T.case.bench, cell: ({ l }) => l.bench_label ?? "—" },
                  { key: "court", header: T.case.court, cell: ({ l }) => l.court_no ?? "—" },
                  {
                    key: "item",
                    header: T.case.item,
                    cell: ({ l }) => (
                      <>
                        {l.printed_sr ?? l.sr_no}
                        {l.is_connected ? <span className="muted"> ({T.case.connected})</span> : null}
                      </>
                    ),
                  },
                  { key: "section", header: T.case.section, cell: ({ l }) => l.section ?? "—" },
                  { key: "codes", header: T.case.counselCodes, cell: ({ l }) => <span className="mono">{l.counsel_codes.join("; ") || "—"}</span> },
                  { key: "remarks", header: T.case.remarks, cell: ({ l }) => l.remarks ?? "—" },
                ]}
              />
              <Pagination offset={lOffset} limit={PAGE} total={listings.data.total} onChange={setLOffset} />
            </>
          )
        ) : null}
      </section>
    </div>
  );
}
