"use client";

/**
 * The Orders tab (design portal-cases, decisions 10 and 15; portal-ui-redesign, decisions 7 and 10.12): each order is
 * the collapsible order row shared with the claim modal — the date in the fixed leading column, the kind or order
 * details and the number; expanded, Print and Download PDF (by `documents.view` / `documents.download`) and the stored
 * PDF inline while `INLINE_PDF` is true, else "Open in a new tab" and Download. The relay keeps the API's nosniff and
 * sandbox headers. An order not stored says "not yet published" or "fetch pending". Under each row, always: the judge
 * and "Next date read", the order's own reading in plain words with the court's sentence (design portal-next-dates,
 * decision 11); never the review state or the rule code. The court's sentence sits under "What the Order Says",
 * which shows the order read into its parts by rules where it has been read (design order-sections, decision 19), or
 * the reading's state as the server names it (design order-sections-review-advisories, decision 15).
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { OrderRow } from "@/components/claim/OrderRow";
import { EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { Order, OrderList } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { readingLabel } from "@/lib/nextDates";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";

import { OrderNotRead, OrderSays } from "./OrderSays";
import s from "./case.module.css";

/** The relay URL of an order's PDF. */
export function fileUrl(caseRef: string, orderId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend${apiCasePath(caseRef)}/orders/${encodeURIComponent(orderId)}/file?disposition=${disposition}`;
}

/** The relay URL of a document's file. */
export function documentUrl(documentId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend/documents/${encodeURIComponent(documentId)}/file?disposition=${disposition}`;
}

/**
 * Decision 11: the reading of one order (the date in bold, its words). Under it "What the Order Says" (design
 * order-sections, decision 19), by the server's `reading_state` (design order-sections-review-advisories, decision
 * 15): `read`, the reading itself, loaded when opened; not read yet, scanned, text not taken from the PDF, or not read
 * into parts, that state in words with the court's sentence; `withheld` (the caller may not open the PDF) or no
 * stored PDF, the court's sentence alone. The portal makes no permission decision of its own here.
 */
export function OrderReading({ order, caseRef }: { order: Order; caseRef?: string }) {
  const reading = readingLabel(order);
  const state = order.reading_state ?? null;
  let says: ReactNode = null;
  if (caseRef && state === "read" && order.reading) {
    says = <OrderSays caseRef={caseRef} order={order} />;
  } else if (caseRef && state && state !== "read" && state !== "withheld") {
    says = <OrderNotRead state={state} phrase={order.next_date_phrase} />;
  } else if (order.next_date_phrase) {
    says = <p>{T.nd.quoted(order.next_date_phrase)}</p>;
  }
  if (!reading && !says) return <span className="muted">—</span>;
  return (
    <div>
      {reading?.date ? <strong>{reading.date}</strong> : null}
      {reading ? reading.date ? <div className="muted">{reading.words}</div> : <span>{reading.words}</span> : null}
      {says ? <SaysDisclosure lazy={state === "read" && !!order.reading}>{says}</SaysDisclosure> : null}
    </div>
  );
}

/**
 * The "What the Order Says" disclosure: a reading is fetched only once it is first opened (`lazy`); the court's
 * sentence alone is in the page from the start, as before.
 */
function SaysDisclosure({ lazy, children }: { lazy: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  return (
    <details open={open}>
      <summary
        onClick={(e) => {
          e.preventDefault();
          setOpen(!open);
          setOpened(true);
        }}
      >
        {T.nd.says}
      </summary>
      {!lazy || opened ? children : null}
    </details>
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
          <EmptyState title={T.case.noOrdersTitle}>{T.case.noOrders}</EmptyState>
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
                        <span className="muted">{T.nd.readCol}:</span> <OrderReading order={o} caseRef={caseRef} />
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
