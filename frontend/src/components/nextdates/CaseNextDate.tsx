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
import { Badge, Button, EmptyState, ErrorBanner, HearingDate, Loading, Notice, Pagination, DataTable } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { CaseDetail, CaseNextDate, CaseNextDateList, NextDateReviewList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate } from "@/lib/format";
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
          {/* design next-hearing-highlight, decisions 5 and 11: a pending suggestion is outlined and says Suggested */}
          <div className="row">
            <HearingDate
              date={row.next_date}
              status={c.status.status}
              kind={row.review_status === "pending" ? "suggested" : "firm"}
              size="md"
            />
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
            <DataTable
              caption={T.nd.section}
              rows={list.data.items}
              rowKey={(row) => row.id}
              columns={[
                {
                  key: "date",
                  header: T.nd.colDate,
                  primary: true,
                  cell: (row) => (
                    <>
                      <strong>{formatDate(row.next_date)}</strong>
                      {row.ref_no ? <div className="mono">{row.ref_no}</div> : null}
                      {row.effective ? (
                        <div>
                          <Badge tone="success">{T.nd.usedForCalendar}</Badge>
                        </div>
                      ) : null}
                    </>
                  ),
                },
                { key: "source", header: T.nd.colSource, cell: (row) => sourceLabel(row.source) },
                { key: "status", header: T.nd.colStatus, cell: (row) => statusLabel(row.review_status, { canAct }) },
                {
                  key: "order",
                  header: T.nd.colOrder,
                  cell: (row) =>
                    row.order ? (
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
                    ),
                },
                { key: "by", header: T.nd.colBy, cell: (row) => <By row={row} /> },
                { key: "note", header: T.nd.colNote, cell: (row) => row.note ?? "—" },
              ]}
            />
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}
