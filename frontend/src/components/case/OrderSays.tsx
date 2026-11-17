"use client";

/**
 * "What the Order Says" (design order-sections, decision 19): an order of the case read into its parts by rules, with
 * no AI, loaded when the disclosure opens (`GET /cases/{ref}/orders/{id}/sections`).
 *
 * - Badges: Judgment or Final Order, Procedural, Registrar Order, and Common Order with the printed case number.
 * - An off-template order says it does not follow the usual layout and is shown as printed.
 * - A judgment or final order shows, above the text: the Outcome, the Directions to the State (compliance only) with
 *   their time limit in words and Due By when the order dates it, the Acts and Provisions Cited, the Judgments Cited and
 *   the Parts found; each item's page opens the stored PDF at that page (`…/file?disposition=inline#page=N`), only for a
 *   caller who may view the PDF (the same rule as the Orders row's View).
 * - The cleaned text without the cause title, addresses or advocates, paragraphs as printed, with the next-date
 *   sentence of the order's reading marked; when it is not found, the sentence follows the text as before. Long texts
 *   sit in the kit's `ScrollBox`.
 * - By the server's `reading_state` (design order-sections-review-advisories, decision 15): not read yet, "Not Read
 *   Yet"; no text layer, "Scanned, Not Read"; text not taken from the PDF, "Text Could Not Be Read"; text not read into
 *   parts, "Not Read Into Parts"; every state still shows the next-date sentence. Page links need no client-side
 *   permission test: a reading is only ever served to a caller who may open the PDF.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode } from "react";

import { Badge, ErrorBanner, Loading, ScrollBox } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { Order, OrderReadingState, OrderSections } from "@/lib/api/types";
import { labelFor } from "@/lib/displayLabels";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";

import { fileUrl } from "./Orders";
import s from "./case.module.css";

/** A body longer than this, or any judgment or final order, scrolls in its own box. */
const SCROLL_FROM = 1500;

export function sectionsUrl(caseRef: string, orderId: string): string {
  return `${apiCasePath(caseRef)}/orders/${encodeURIComponent(orderId)}/sections`;
}

/** The PDF at page `n`, opened inline in a new tab. */
export function pageUrl(caseRef: string, orderId: string, n: number): string {
  return `${fileUrl(caseRef, orderId, "inline")}#page=${n}`;
}

function PageLink({ caseRef, orderId, page, what }: { caseRef: string; orderId: string; page?: number | null; what: string }) {
  if (!page) return null;
  return (
    <a href={pageUrl(caseRef, orderId, page)} target="_blank" rel="noopener noreferrer" aria-label={T.os.openAria(what, page)}>
      {T.os.pageLink(page)}
    </a>
  );
}

/** The next-date sentence's span inside the paragraph's span, if it falls in it. */
function marked(text: string, start: number, mark: number[] | null | undefined): ReactNode {
  if (!mark || mark.length !== 2) return text;
  const [m0, m1] = mark as [number, number];
  const end = start + text.length;
  if (m1 <= start || m0 >= end) return text;
  const a = Math.max(m0, start) - start;
  const b = Math.min(m1, end) - start;
  return (
    <>
      {text.slice(0, a)}
      <mark>{text.slice(a, b)}</mark>
      {text.slice(b)}
    </>
  );
}

function Body({ data }: { data: OrderSections }) {
  const mark = data.next_date.txt;
  const paragraphs = data.paragraphs.length
    ? data.paragraphs
    : [{ txt: [0, data.body_text.length], label: null, part: "body", page: null }];
  const text = (
    <div className={s.orderSaysBody}>
      {paragraphs.map((p, i) => {
        const [t0, t1] = (p.txt ?? [0, 0]) as [number, number];
        return <p key={i}>{marked(data.body_text.slice(t0, t1), t0, mark)}</p>;
      })}
    </div>
  );
  const long = data.form !== "interim" || data.body_text.length > SCROLL_FROM;
  return long ? <ScrollBox label={T.os.bodyTitle}>{text}</ScrollBox> : text;
}

export function OrderSaysView({ caseRef, order, data }: { caseRef: string; order: Order; data: OrderSections }) {
  const decided = data.form === "judgment" || data.form === "final";
  const compliance = data.directions.filter((d) => d.kind === "compliance");
  const link = (page: number | null | undefined, what: string) => (
    <PageLink caseRef={caseRef} orderId={order.id} page={page} what={what} />
  );
  return (
    <div className={s.orderSays} role="region" aria-label={T.os.regionLabel}>
      <div className={s.orderSaysBadges}>
        {data.form === "judgment" ? <Badge tone="info">{T.os.badges.judgment}</Badge> : null}
        {data.form === "final" ? <Badge tone="info">{T.os.badges.final}</Badge> : null}
        {data.registrar ? <Badge>{T.os.badges.registrar}</Badge> : null}
        {data.procedural ? <Badge>{T.os.badges.procedural}</Badge> : null}
        {data.common_order ? (
          <Badge wrap>
            {data.common_order.printed_case_no ? T.os.commonBadge(data.common_order.printed_case_no) : T.os.badges.common}
          </Badge>
        ) : null}
      </div>
      {data.layout === "whole" ? <p className="muted">{T.os.offTemplateNote}</p> : null}
      {decided ? (
        <dl className={s.orderSaysFacts}>
          {data.outcome ? (
            <>
              <dt>{T.os.outcomeTitle}</dt>
              <dd>
                <strong>{labelFor(T.os.outcomes, data.outcome.value)}</strong>{" "}
                <span className="muted">{T.nd.quoted(data.outcome.text)}</span> {link(data.outcome.page, T.os.outcomeTitle)}
              </dd>
            </>
          ) : null}
          {compliance.length ? (
            <>
              <dt>{T.os.directionsTitle}</dt>
              <dd>
                <ul>
                  {compliance.map((d, i) => (
                    <li key={i}>
                      {d.text}
                      {d.period ? <div className="muted">{T.os.timeLimitNote(d.period.n, d.period.unit, d.period.from)}</div> : null}
                      {d.due_on ? <Badge tone="warning">{T.os.dueBy(formatDate(d.due_on))}</Badge> : null}{" "}
                      {link(d.page, T.os.directionsTitle)}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          ) : null}
          {data.acts.length ? (
            <>
              <dt>{T.os.actsTitle}</dt>
              <dd>
                <ul>
                  {data.acts.map((a, i) => (
                    <li key={i}>
                      {T.os.provisionsLine(a.kind, a.provisions)} · {a.act} {link(a.page, a.act)}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          ) : null}
          {data.judgments.length ? (
            <>
              <dt>{T.os.judgmentsTitle}</dt>
              <dd>
                <ul>
                  {data.judgments.map((j, i) => (
                    <li key={i}>
                      {T.os.citedAs(j.citation, j.case_name)} {link(j.page, j.citation)}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          ) : null}
          {data.parts.length ? (
            <>
              <dt>{T.os.partsTitle}</dt>
              <dd className={s.orderSaysParts}>
                {data.parts.map((p, i) => {
                  const name = labelFor(T.os.parts, p.part);
                  return (
                    <Fragment key={i}>
                      {p.page ? (
                        <a href={pageUrl(caseRef, order.id, p.page)} target="_blank" rel="noopener noreferrer" aria-label={T.os.openAria(name, p.page)}>
                          {name}
                        </a>
                      ) : (
                        <span>{name}</span>
                      )}
                    </Fragment>
                  );
                })}
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
      <Body data={data} />
      {data.next_date.txt ? (
        <p className="muted">{T.os.sentenceNote}</p>
      ) : data.next_date.phrase ? (
        <p>{T.nd.quoted(data.next_date.phrase)}</p>
      ) : null}
    </div>
  );
}

/** The states shown in words: an order with a stored PDF the caller may open and no reading. */
export type NotReadState = Exclude<OrderReadingState, "read" | "withheld">;

const NOT_READ: Record<NotReadState, { title: string; note: string }> = {
  not_read_yet: { title: T.os.notReadTitle, note: T.os.notReadNote },
  scanned: { title: T.os.scannedTitle, note: T.os.scannedNote },
  text_failed: { title: T.os.textFailedTitle, note: T.os.textFailedNote },
  reading_failed: { title: T.os.readingFailedTitle, note: T.os.readingFailedNote },
};

/** Not read (yet, or ever): the state in words, then the order's next-date sentence as before. */
export function OrderNotRead({ state, phrase }: { state: NotReadState; phrase?: string | null }) {
  const words = NOT_READ[state] ?? NOT_READ.not_read_yet;
  return (
    <div className={s.orderSays}>
      <strong>{words.title}</strong>
      <p className="muted">{words.note}</p>
      {phrase ? <p>{T.nd.quoted(phrase)}</p> : null}
    </div>
  );
}

/** The state of a 404 `no_reading`: the server's `reading_state`, else read from its `text_status`. */
function notReadState(extra: Record<string, unknown>): NotReadState {
  const named = extra.reading_state;
  if (typeof named === "string" && named in NOT_READ) return named as NotReadState;
  if (extra.text_status === "none") return "scanned";
  if (extra.text_status === "failed") return "text_failed";
  return "not_read_yet";
}

export function OrderSays({ caseRef, order }: { caseRef: string; order: Order }) {
  const q = useQuery({
    queryKey: [...caseKey(caseRef), "orders", order.id, "sections"],
    queryFn: () => api<OrderSections>(sectionsUrl(caseRef, order.id)),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  if (q.isPending) return <Loading />;
  if (q.error) {
    if (q.error instanceof ApiError && q.error.code === "no_reading") {
      return <OrderNotRead state={notReadState(q.error.extra)} phrase={order.next_date_phrase} />;
    }
    return <ErrorBanner error={q.error} onRetry={() => q.refetch()} />;
  }
  return <OrderSaysView caseRef={caseRef} order={order} data={q.data} />;
}
