"use client";

/**
 * The court-record view of a cited court order (design assistant, decision 11): `/assistant/orders/[orderId]?m=`,
 * opened from a source of the reader's own answer when the order belongs to a case they cannot open. It shows the
 * order (number, date, kind, judge) and the case's court-public facts, never the owner, custody, stage, notes,
 * documents or `ref_no`, and says "This is the court's public record. You cannot open this case in ASLMS." The order
 * opens from the assistant's file route (the API checks the citation again and records each opening). Without a
 * citation of the order in the reader's own answer the API answers 404 and the page says so.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Card, DefinitionList, EmptyState, ErrorBanner, Loading, Notice, PageHeader, buttonClass } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import type { AssistantCourtOrderView } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import s from "./assistant.module.css";

const A = T.assistant;
const F = A.facts;

function list(values: string[]): string {
  return values.length ? values.join("; ") : "—";
}

export function CourtOrderView({ orderId, messageId }: { orderId: string; messageId: string | null }) {
  const query = useQuery({
    queryKey: ["assistant", "court-order", orderId, messageId ?? ""],
    queryFn: () =>
      api<AssistantCourtOrderView>(`/assistant/court-orders/${encodeURIComponent(orderId)}`, {
        query: { message: messageId ?? undefined },
      }),
    enabled: !!messageId,
  });
  if (!messageId || (query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <div className="stack">
        <PageHeader title={A.courtRecord} />
        <EmptyState>{A.notCited}</EmptyState>
      </div>
    );
  }
  if (query.isPending) return <Loading />;
  if (query.error || !query.data) return <ErrorBanner error={query.error} onRetry={() => query.refetch()} />;
  const { order, case: c, case_visible } = query.data;
  const file = (disposition: "inline" | "attachment") =>
    `/api/backend/assistant/court-orders/${encodeURIComponent(order.id)}/file?message=${encodeURIComponent(messageId)}&disposition=${disposition}`;
  return (
    <div className="stack">
      <PageHeader
        title={A.courtRecordTitle(c.case_no_text ?? c.cnr ?? A.courtRecord)}
        titleClassName={c.case_no_text ? "cno" : "mono"}
        subtitle={`${A.orderKinds[order.kind] ?? order.kind} · ${formatDate(order.order_date)}`}
        actions={
          <>
            {case_visible && c.cnr ? (
              <Link className={buttonClass("secondary")} href={casePath(c.cnr)}>
                {A.openCase}
              </Link>
            ) : null}
            <a className={buttonClass("secondary")} href={file("attachment")}>
              {A.downloadOrder}
            </a>
          </>
        }
        primary={
          <a className={buttonClass("primary")} href={file("inline")} target="_blank" rel="noopener noreferrer">
            {A.openOrder}
          </a>
        }
      />
      {!case_visible ? <Notice>{A.courtRecordNotice}</Notice> : null}
      <div className={s.facts}>
        <Card title={A.order}>
          <DefinitionList
            items={[
              [F.orderNo, order.order_no],
              [F.orderDate, formatDate(order.order_date)],
              [F.kind, A.orderKinds[order.kind] ?? order.kind],
              [F.judge, order.judge],
            ]}
          />
        </Card>
        <Card title={A.courtRecord}>
          <DefinitionList
            items={[
              [F.caseNo, c.case_no_text ? <span className="cno">{c.case_no_text}</span> : null],
              [F.cnr, c.cnr ? <span className="mono">{c.cnr}</span> : null],
              [F.filingNo, c.filing_no_text],
              [F.court, c.court],
              [F.bench, c.bench],
              [F.caseType, c.case_type],
              [F.year, c.year],
              [F.status, c.status ? (T.inbox.statuses[c.status] ?? c.status) : null],
              [F.parties, list(c.parties)],
              [F.advocates, list(c.advocates)],
              [F.acts, list(c.acts)],
              [F.lastHearing, formatDate(c.last_hearing_date)],
              [F.nextHearing, formatDate(c.next_hearing_date)],
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
