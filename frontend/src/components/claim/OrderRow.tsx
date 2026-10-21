"use client";

/**
 * One order as a collapsible row (design portal-ui-redesign, decision 7; shared with the case page's Orders tab in
 * round 3): the date in the fixed leading column, the kind or the order details, and a chevron. Expanded, it shows a
 * toolbar with Print and Download PDF (by `documents.view` and `documents.download`) and the stored PDF inline in an
 * `<iframe>` of the relay's `…/orders/{id}/file?disposition=inline`, mounted only on the first expand and only while
 * `INLINE_PDF` is true. The browser's own viewer shows it: no PDF library; the API's `Content-Security-Policy:
 * sandbox` and `nosniff` stay. Print opens the same inline address in a new tab, where the browser's viewer prints
 * (the portal cannot script into the sandboxed frame, so it never calls `print()` on it). When the PDF is not stored the
 * row says "Not yet published" or "Fetch pending"; when `INLINE_PDF` is false the expanded row offers "Open in a new
 * tab" and Download instead. `meta` (the case page's Orders tab: the judge and the order's next-date reading) shows
 * under the row's summary, always.
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { fileState, fileUrl } from "@/components/case/Orders";
import { buttonClass, Collapsible, EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe } from "@/lib/api/hooks";
import type { Order, OrderList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { INLINE_PDF } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { PAGE } from "@/lib/params";
import { apiCasePath } from "@/lib/refs";

import s from "./claim.module.css";

export function OrderRow({
  caseRef,
  order,
  meta,
  label,
}: {
  caseRef: string;
  order: Order;
  meta?: ReactNode;
  /** In place of the order's details in the summary (the Overview's Latest order card, which shows them above). */
  label?: ReactNode;
}) {
  const me = useMe();
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  const stored = order.download_status === "stored";
  const date = formatDate(order.order_date);
  const inline = fileUrl(caseRef, order.id, "inline");
  const summary = (
    <span className={s.orderHead}>
      <span className={s.orderDate}>{date}</span>
      {label ? (
        <span>{label}</span>
      ) : (
        <span>
          {order.order_details || order.kind}
          {order.order_no ? <span className="muted"> · {order.order_no}</span> : null}
        </span>
      )}
    </span>
  );
  return (
    <Collapsible summary={summary} after={meta}>
      {!stored ? (
        <p className="muted">{fileState(order.download_status)}</p>
      ) : (
        <>
          <div className={s.orderToolbar}>
            {canView && INLINE_PDF ? (
              <a className={buttonClass("secondary", "sm")} href={inline} target="_blank" rel="noopener noreferrer">
                {T.claim.print}
              </a>
            ) : null}
            {canView && !INLINE_PDF ? (
              <a className={buttonClass("secondary", "sm")} href={inline} target="_blank" rel="noopener noreferrer">
                {T.claim.openNewTab}
              </a>
            ) : null}
            {canDownload ? (
              <a className={buttonClass("secondary", "sm")} href={fileUrl(caseRef, order.id, "attachment")} download>
                {T.claim.downloadPdf}
              </a>
            ) : null}
          </div>
          {canView && INLINE_PDF ? <iframe className={s.frame} src={inline} title={T.claim.orderFrame(date)} /> : null}
        </>
      )}
    </Collapsible>
  );
}

/**
 * The Orders tab of the modal: every order of the case (newest first, as the API orders them) as a collapsible row,
 * paged by `PAGE` with the kit's `Pagination`, as the case page's Orders tab (design portal-ui-polish, decision 7).
 */
export function OrderRows({ caseRef }: { caseRef: string }) {
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "orders", "page", offset],
    queryFn: () => api<OrderList>(`${apiCasePath(caseRef)}/orders`, { query: { limit: PAGE, offset } }),
  });
  if (list.isPending) return <Loading />;
  if (list.error) return <ErrorBanner error={list.error} onRetry={() => list.refetch()} />;
  if (list.data.items.length === 0) return <EmptyState>{T.case.noOrders}</EmptyState>;
  return (
    <div className="stack">
      <div className={s.orders}>
        {list.data.items.map((o) => (
          <OrderRow key={o.id} caseRef={caseRef} order={o} />
        ))}
      </div>
      <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
    </div>
  );
}
