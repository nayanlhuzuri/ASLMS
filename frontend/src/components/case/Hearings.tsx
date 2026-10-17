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
import { EmptyState, ErrorBanner, Loading, Pagination, Table } from "@/components/ui";
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
              <Table caption={T.case.hearings}>
                <thead>
                  <tr>
                    <th scope="col">{T.case.businessDate}</th>
                    <th scope="col">{T.case.purposeCol}</th>
                    <th scope="col">{T.case.bench}</th>
                    <th scope="col">{T.case.nextDate}</th>
                    <th scope="col">{T.case.business}</th>
                  </tr>
                </thead>
                <tbody>
                  {hearings.data.items.map((h, i) => (
                    <tr key={i}>
                      <td>{formatDate(h.business_date ?? h.hearing_date)}</td>
                      <td>{h.purpose ?? "—"}</td>
                      <td>
                        {h.bench_text ?? "—"}
                        {h.judge_designation ? <div className="muted">{h.judge_designation}</div> : null}
                      </td>
                      <td>{formatDate(h.next_date)}</td>
                      <td>
                        {h.business_text ?? "—"}
                        {h.short_order_text ? (
                          <div className="muted">
                            {T.case.shortOrder}: {h.short_order_text}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
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
              <Table caption={T.case.listings}>
                <thead>
                  <tr>
                    <th scope="col">{T.case.listDate}</th>
                    <th scope="col">{T.case.listType}</th>
                    <th scope="col">{T.case.bench}</th>
                    <th scope="col">{T.case.court}</th>
                    <th scope="col">{T.case.item}</th>
                    <th scope="col">{T.case.section}</th>
                    <th scope="col">{T.case.counselCodes}</th>
                    <th scope="col">{T.case.remarks}</th>
                  </tr>
                </thead>
                <tbody>
                  {listings.data.items.map((l, i) => (
                    <tr key={i}>
                      <td>
                        {formatDate(l.list_date)}
                        <div>
                          <Link href={causelistHref(l.list_date, l.bench_id)}>{T.causelist.openCauselist}</Link>
                        </div>
                      </td>
                      <td>{l.list_type}</td>
                      <td>{l.bench_label ?? "—"}</td>
                      <td>{l.court_no ?? "—"}</td>
                      <td>
                        {l.printed_sr ?? l.sr_no}
                        {l.is_connected ? <span className="muted"> ({T.case.connected})</span> : null}
                      </td>
                      <td>{l.section ?? "—"}</td>
                      <td className="mono">{l.counsel_codes.join("; ") || "—"}</td>
                      <td>{l.remarks ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Pagination offset={lOffset} limit={PAGE} total={listings.data.total} onChange={setLOffset} />
            </>
          )
        ) : null}
      </section>
    </div>
  );
}
