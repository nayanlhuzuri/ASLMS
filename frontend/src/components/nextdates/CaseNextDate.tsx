"use client";

/**
 * The case page's next dates (design portal-next-dates, decisions 8 and 10; plan §5.3 "the latest order with the next
 * date read"):
 * - `NextDateBlock`, the body of the Overview card "Next date from orders": the date in use with where it came from,
 *   the court's sentence and the note; "Waiting for you" with the case's review items when `next_dates_to_review` is
 *   above zero (read from `GET /next-dates/review?q=<case id>`); "Enter next date" by `workflow.next_dates`;
 * - `NextDatesSection`, the Hearings tab's "Next dates": `GET /cases/{ref}/next-dates`, newest first, with the row used
 *   for the calendar marked.
 * What may be done comes from the server; the browser never works out review state or who may act.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { fileUrl } from "@/components/case/Orders";
import { Badge, Button, EmptyState, ErrorBanner, Loading, Notice, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { CaseDetail, CaseNextDate, CaseNextDateList, NextDateReviewList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, hearingBadge } from "@/lib/format";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { originLine, sourceLabel, statusLabel } from "@/lib/nextDates";
import { PAGE } from "@/lib/params";
import { apiCasePath, casePath } from "@/lib/refs";

import { EnterNextDate, type DialogOutcome } from "./Dialogs";
import s from "./nextdates.module.css";
import { ReviewTable } from "./ReviewList";

function WaitingForYou({ caseRef, c, outcome }: { caseRef: string; c: CaseDetail; outcome: DialogOutcome }) {
  const items = useQuery({
    queryKey: [...caseKey(caseRef), "next-dates", "review"],
    queryFn: () => api<NextDateReviewList>("/next-dates/review", { query: { q: c.id, limit: PAGE } }),
  });
  return (
    <div className={s.panel} role="group" aria-label={T.nd.waiting}>
      <h4>{T.nd.waiting}</h4>
      {items.isPending ? <Loading /> : null}
      <ErrorBanner error={items.error} onRetry={() => items.refetch()} messages={NEXT_DATE_ERRORS} />
      {items.data && items.data.items.length > 0 ? (
        <ReviewTable items={items.data.items} caption={T.nd.waiting} showCase={false} {...outcome} />
      ) : null}
    </div>
  );
}

export function NextDateBlock({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [stale, setStale] = useState<unknown>(null);
  const row = c.next_date_from_orders ?? null;
  const badge = row ? hearingBadge(row.next_date) : null;
  const outcome: DialogOutcome = {
    onDone: (text) => {
      setStale(null);
      setNotice(text);
    },
    onStale: (err) => {
      setNotice(null);
      setStale(err);
    },
  };
  return (
    <>
      {notice ? <Notice>{notice}</Notice> : null}
      <ErrorBanner error={stale} messages={NEXT_DATE_ERRORS} />
      {row ? (
        <>
          <div className="row">
            <strong>{formatDate(row.next_date)}</strong>
            {badge === "critical" ? <Badge tone="danger">{T.case.within48}</Badge> : null}
            {badge === "week" ? <Badge>{T.case.thisWeek}</Badge> : null}
          </div>
          <div className="muted">{originLine(row)}</div>
          {row.order?.phrase ? (
            <details>
              <summary>{T.nd.says}</summary>
              <p>{T.nd.quoted(row.order.phrase)}</p>
            </details>
          ) : null}
          {row.note ? (
            <div>
              {T.nd.colNote}: {row.note}
            </div>
          ) : null}
        </>
      ) : (
        <p className="muted">{T.nd.noneYet}</p>
      )}
      {(c.next_dates_to_review ?? 0) > 0 ? <WaitingForYou caseRef={caseRef} c={c} outcome={outcome} /> : null}
      {c.workflow.next_dates ? (
        <>
          <div className="row">
            <Button variant="secondary" onClick={() => setOpen(true)}>
              {T.nd.enterNext}
            </Button>
          </div>
          <EnterNextDate
            caseRef={caseRef}
            name={c.identity.case_no_text || c.ref_no}
            open={open}
            onClose={() => setOpen(false)}
            {...outcome}
          />
        </>
      ) : null}
      <Link href={`${casePath(caseRef, "hearings")}#next-dates`}>{T.nd.allNextDates}</Link>
    </>
  );
}

function By({ row }: { row: CaseNextDate }) {
  if (row.source === "manual" && row.created_by?.name) return <>{T.nd.byOn(row.created_by.name, formatDate(row.created_at))}</>;
  if (row.reviewed_at && row.reviewed_by?.name) return <>{T.nd.byOn(row.reviewed_by.name, formatDate(row.reviewed_at))}</>;
  return <span className="muted">—</span>;
}

export function NextDatesSection({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const detail = useCase(caseRef);
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "next-dates", offset],
    queryFn: () => api<CaseNextDateList>(apiCasePath(caseRef, "next-dates"), { query: { limit: PAGE, offset } }),
  });
  const canAct = !!detail.data?.workflow.next_dates;
  const canView = can(me.data, "documents.view");
  return (
    <section className="stack" aria-label={T.nd.section} id="next-dates">
      <h2>{T.nd.section}</h2>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.nd.noNextDates}</EmptyState>
        ) : (
          <>
            <Table caption={T.nd.section}>
              <thead>
                <tr>
                  <th scope="col">{T.nd.colDate}</th>
                  <th scope="col">{T.nd.colSource}</th>
                  <th scope="col">{T.nd.colStatus}</th>
                  <th scope="col">{T.nd.colOrder}</th>
                  <th scope="col">{T.nd.colBy}</th>
                  <th scope="col">{T.nd.colNote}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{formatDate(row.next_date)}</strong>
                      {row.ref_no ? <div className="mono">{row.ref_no}</div> : null}
                      {row.effective ? (
                        <div>
                          <Badge tone="success">{T.nd.usedForCalendar}</Badge>
                        </div>
                      ) : null}
                    </td>
                    <td>{sourceLabel(row.source)}</td>
                    <td>{statusLabel(row.review_status, { canAct })}</td>
                    <td>
                      {row.order ? (
                        <>
                          <span className="mono">{row.order.order_no}</span> · {formatDate(row.order.order_date)}
                          {row.order.document_id && canView ? (
                            <div>
                              <a href={fileUrl(caseRef, row.order.id, "inline")} target="_blank" rel="noopener noreferrer">
                                {T.nd.viewOrder}
                              </a>
                            </div>
                          ) : null}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <By row={row} />
                    </td>
                    <td>{row.note ?? "—"}</td>
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
