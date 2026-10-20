"use client";

/**
 * The Orders tab (design portal-cases, decisions 10 and 15; portal-ui-redesign, decisions 7 and 10.12): each order is
 * the collapsible order row shared with the claim modal — the date in the fixed leading column, the kind or order
 * details and the number; expanded, Print and Download PDF (by `documents.view` / `documents.download`) and the stored
 * PDF inline while `INLINE_PDF` is true, else "Open in a new tab" and Download. The relay keeps the API's nosniff and
 * sandbox headers. An order not stored says "not yet published" or "fetch pending". Under each row, always: the judge
 * and "Next date read", the order's own reading in plain words with the court's sentence (design portal-next-dates,
 * decision 11); never the review state or the rule code.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { OrderRow } from "@/components/claim/OrderRow";
import { EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { OrderList } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { readingLabel } from "@/lib/nextDates";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";

import s from "./case.module.css";

/** The relay URL of an order's PDF. */
export function fileUrl(caseRef: string, orderId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend${apiCasePath(caseRef)}/orders/${encodeURIComponent(orderId)}/file?disposition=${disposition}`;
}

/** The relay URL of a document's file. */
export function documentUrl(documentId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend/documents/${encodeURIComponent(documentId)}/file?disposition=${disposition}`;
}

/** Decision 11: the reading of one order (the date in bold, its words, the court's sentence under "What the order says"). */
export function OrderReading({ order }: { order: { next_date_status?: string | null; next_date_found?: string | null; next_date_phrase?: string | null } }) {
  const reading = readingLabel(order);
  if (!reading) return <span className="muted">—</span>;
  return (
    <div>
      {reading.date ? <strong>{reading.date}</strong> : null}
      {reading.date ? <div className="muted">{reading.words}</div> : <span>{reading.words}</span>}
      {order.next_date_phrase ? (
        <details>
          <summary>{T.nd.says}</summary>
          <p>{T.nd.quoted(order.next_date_phrase)}</p>
        </details>
      ) : null}
    </div>
  );
}

export function fileState(status: string): string {
  if (status === "stored") return "";
  if (status === "not_available" || status === "not_published") return T.case.notPublished;
  return T.case.fetchPending;
}

export function Orders({ caseRef }: { caseRef: string }) {
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "orders", "page", offset],
    queryFn: () => api<OrderList>(`${apiCasePath(caseRef)}/orders`, { query: { limit: PAGE, offset } }),
  });
  return (
    <section className="stack" aria-label={T.case.orders}>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.case.noOrders}</EmptyState>
        ) : (
          <>
            <div className={s.orderList}>
              {list.data.items.map((o) => (
                <OrderRow
                  key={o.id}
                  caseRef={caseRef}
                  order={o}
                  meta={
                    <div className={s.orderMeta} aria-label={T.case.orderMeta} role="group">
                      {o.order_judge_name ? (
                        <span>
                          {T.case.judge}: {o.order_judge_name}
                        </span>
                      ) : null}
                      <div className={s.orderReading}>
                        <span className="muted">{T.nd.readCol}:</span> <OrderReading order={o} />
                      </div>
                    </div>
                  }
                />
              ))}
            </div>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}
