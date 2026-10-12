"use client";

/**
 * The Orders tab (design portal-cases, decisions 10 and 15): number, date, kind, judge and the file's state; View
 * (inline, `documents.view`) opens the API's file in a new tab through the relay, which keeps the API's nosniff and
 * sandbox headers; Download (`documents.download`) saves it. An order not stored says "not yet published" or "fetch
 * pending". Order files are PDFs: View follows `INLINE_PDF` (design portal-cases-followups, decision 10).
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { EmptyState, ErrorBanner, Loading, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe } from "@/lib/api/hooks";
import type { OrderList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { canViewInline, pdfDownloadOnly } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";

/** The relay URL of an order's PDF. */
export function fileUrl(caseRef: string, orderId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend${apiCasePath(caseRef)}/orders/${encodeURIComponent(orderId)}/file?disposition=${disposition}`;
}

/** The relay URL of a document's file. */
export function documentUrl(documentId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend/documents/${encodeURIComponent(documentId)}/file?disposition=${disposition}`;
}

const ORDER_MIME = "application/pdf";

export function fileState(status: string): string {
  if (status === "stored") return "";
  if (status === "not_available" || status === "not_published") return T.case.notPublished;
  return T.case.fetchPending;
}

export function Orders({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "orders", "page", offset],
    queryFn: () => api<OrderList>(`${apiCasePath(caseRef)}/orders`, { query: { limit: PAGE, offset } }),
  });
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  return (
    <section className="stack" aria-label={T.case.orders}>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.case.noOrders}</EmptyState>
        ) : (
          <>
            <Table caption={T.case.orders}>
              <thead>
                <tr>
                  <th scope="col">{T.case.orderNo}</th>
                  <th scope="col">{T.case.orderDate}</th>
                  <th scope="col">{T.case.kind}</th>
                  <th scope="col">{T.case.judge}</th>
                  <th scope="col">{T.case.fileStatus}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((o) => (
                  <tr key={o.id}>
                    <td className="mono">{o.order_no}</td>
                    <td>{formatDate(o.order_date)}</td>
                    <td>{o.kind}</td>
                    <td>{o.order_judge_name ?? "—"}</td>
                    <td>
                      {o.download_status === "stored" ? (
                        <div className="row">
                          {canView && canViewInline(ORDER_MIME) ? (
                            <a href={fileUrl(caseRef, o.id, "inline")} target="_blank" rel="noopener noreferrer">
                              {T.case.view}
                            </a>
                          ) : null}
                          {canDownload ? (
                            <a href={fileUrl(caseRef, o.id, "attachment")} download>
                              {T.case.download}
                            </a>
                          ) : null}
                          {canDownload && pdfDownloadOnly(ORDER_MIME) ? (
                            <span className="muted">{T.case.opensAsDownload}</span>
                          ) : null}
                        </div>
                      ) : (
                        <span className="muted">{fileState(o.download_status)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}
