"use client";

/**
 * The case page's next dates (design portal-next-dates, decisions 8 and 10; plan §5.3 "the latest order with the next
 * date read"):
 * - `NextDateBlock`, the body of the Overview card "Next Date From Orders": the date in use as one plain line with
 *   where it came from ("this order" for the latest order, `latestOrderId`; design portal-screen-fixes-work, decisions 9
 *   and 10), the court's sentence and the note; Report Wrong Next Date, Correct It and Enter Next Date in one toolbar;
 *   "Waiting for you" with the case's enter items when `next_dates_to_review` is above zero (read from `GET /next-dates/review?q=<case id>`); "Enter next date" only by `workflow.next_dates`, else
 *   the plain reason when the court has given the date (design next-date-direct, decision 6); Report Wrong Next Date
 *   and Correct It only by `workflow.next_date_report` / `next_date_correct` (decisions 17 to 19), and the "Reported as
 *   possibly wrong" line while a report is open;
 * - `NextDatesSection`, the Hearings tab's "Next dates": `GET /cases/{ref}/next-dates`, newest first, with the row used
 *   for the calendar marked.
 * What may be done comes from the server; the browser never works out review state or who may act.
 */
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { fileUrl } from "@/components/case/Orders";
import { Badge, Button, DataTable, EmptyState, ErrorBanner, Loading, Pagination, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe } from "@/lib/api/hooks";
import type { CaseDetail, CaseNextDate, CaseNextDateList, NextDateReviewList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate } from "@/lib/format";
import { NEXT_DATE_ERRORS, T } from "@/lib/messages";
import { originLine, sourceLabel, statusLabel } from "@/lib/nextDates";
import { PAGE } from "@/lib/params";
import { apiCasePath } from "@/lib/refs";

import { CorrectNextDate, EnterNextDate, ReportWrongNextDate, type DialogOutcome } from "./Dialogs";
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

export function NextDateBlock({ caseRef, c, latestOrderId }: { caseRef: string; c: CaseDetail; latestOrderId?: string | null }) {
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState<"report" | "correct" | null>(() =>
    search?.get("nd") === "correct" && c.workflow.next_date_correct ? "correct" : null,
  );
  const toast = useToast();
  const [stale, setStale] = useState<unknown>(null);
  const row = c.next_date_from_orders ?? null;
  // the reading of the latest order the report and the correction are about (decision 17's row)
  const reading = row && row.source !== "manual" ? row : null;
  const name = c.identity.case_no_text || c.ref_no;
  const outcome: DialogOutcome = {
    onDone: (text) => {
      setStale(null);
      toast(text);
    },
    onStale: (err) => {
      setStale(err);
    },
  };
  return (
    <>
      <ErrorBanner error={stale} messages={NEXT_DATE_ERRORS} />
      {row ? (
        <>
          {/* design next-date-direct, decision 8: a date read from an order is shown directly, around for a period; design
              portal-screen-fixes-work, decision 10: a plain line, the badge being the header's and the rail's */}
          <p className={s.readingLine} data-reading-line="">
            {T.nd.readingLine(
              formatDate(row.next_date),
              originLine(row, latestOrderId),
              !!reading && c.next_hearing?.basis === "around" && c.next_hearing.date === row.next_date,
            )}
          </p>
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
      {c.next_hearing?.reported_at ? (
        <p className="muted" data-reported="true">
          {T.hearing.reported(formatDate(c.next_hearing.reported_at))}
        </p>
      ) : null}
      {(c.next_dates_to_review ?? 0) > 0 ? <WaitingForYou caseRef={caseRef} c={c} outcome={outcome} /> : null}
      {c.workflow.next_dates_blocked === "court_date_fixed" ? <p className="muted">{T.hearing.fixed}</p> : null}
      {/* one toolbar for the three buttons, each by its own flag; it wraps on a phone */}
      {(reading && (c.workflow.next_date_report || c.workflow.next_date_correct)) || c.workflow.next_dates ? (
        <div className={s.toolbar}>
          {reading && c.workflow.next_date_report ? (
            <Button variant="secondary" onClick={() => setDialog("report")}>
              {T.nd.report}
            </Button>
          ) : null}
          {reading && c.workflow.next_date_correct ? (
            <Button variant="secondary" onClick={() => setDialog("correct")}>
              {T.nd.correct}
            </Button>
          ) : null}
          {c.workflow.next_dates ? (
            <Button variant="secondary" onClick={() => setOpen(true)}>
              {T.nd.enterNext}
            </Button>
          ) : null}
        </div>
      ) : null}
      {reading && (c.workflow.next_date_report || c.workflow.next_date_correct) ? (
        <>
          {c.workflow.next_date_report ? (
            <ReportWrongNextDate
              caseRef={caseRef}
              name={name}
              nextDateId={reading.id}
              dateRead={reading.next_date}
              next={c.next_hearing ?? null}
              open={dialog === "report"}
              onClose={() => setDialog(null)}
              {...outcome}
            />
          ) : null}
          {c.workflow.next_date_correct ? (
            <CorrectNextDate
              caseRef={caseRef}
              name={name}
              nextDateId={reading.id}
              dateRead={reading.next_date}
              next={c.next_hearing ?? null}
              reported={!!c.next_hearing?.reported_at}
              open={dialog === "correct"}
              onClose={() => setDialog(null)}
              {...outcome}
            />
          ) : null}
        </>
      ) : null}
      {c.workflow.next_dates ? (
        <EnterNextDate
          caseRef={caseRef}
          name={c.identity.case_no_text || c.ref_no}
          open={open}
          onClose={() => setOpen(false)}
          {...outcome}
        />
      ) : null}
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
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "next-dates", offset],
    queryFn: () => api<CaseNextDateList>(apiCasePath(caseRef, "next-dates"), { query: { limit: PAGE, offset } }),
  });
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
                  // design portal-screen-fixes-work, decision 12: the internal number only as the title, never in sight
                  cell: (row) => (
                    <>
                      <strong title={row.ref_no ?? undefined}>{formatDate(row.next_date)}</strong>
                      {row.effective ? (
                        <div>
                          <Badge tone="success">{T.nd.usedForCalendar}</Badge>
                        </div>
                      ) : null}
                    </>
                  ),
                },
                { key: "source", header: T.nd.colSource, cell: (row) => sourceLabel(row.source) },
                { key: "status", header: T.nd.colStatus, cell: (row) => statusLabel(row.review_status) },
                {
                  key: "order",
                  header: T.nd.colOrder,
                  cell: (row) =>
                    row.order ? (
                      <>
                        <div>{T.nd.orderOf(formatDate(row.order.order_date))}</div>
                        {row.order.order_no ? <div className="muted">{T.nd.orderNo(row.order.order_no)}</div> : null}
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
