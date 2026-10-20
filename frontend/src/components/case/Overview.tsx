"use client";

/**
 * The Overview tab (design portal-ui-redesign, decisions 10.10 and 24; plan §5.3; Annexure B cards), two columns that
 * stack below 1100 px:
 * - Latest order: its date, kind and short text (`order_details`), the collapsible order row with the stored PDF
 *   (decision 7), the order's reading and the next-date block of portal-next-dates (decision 8: the date in use,
 *   "Waiting for you" with Confirm / Not correct, Enter next date by the `next_dates` flag), "All orders →", and the
 *   folded "Show parties, advocates and acts" (the first petitioner and respondent with their advocates, the counsel
 *   codes and the acts, "+ n more" to Parties);
 * - Recent activity: the five latest timeline entries on the timeline rail, "Timeline →";
 * - below, the folded "Ownership and recommendations" (today's Ownership card), and the muted "You see this case as:
 *   …" line from `access_basis`.
 * The next hearing, the file holder, the stage and the owner are in the summary header; the full custody card and the
 * stage history are on the Custody and stage tab.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { OrderRow } from "@/components/claim/OrderRow";
import { NextDateBlock } from "@/components/nextdates/CaseNextDate";
import { Card, Collapsible, ErrorBanner, KvList, Loading } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase } from "@/lib/api/hooks";
import type { CaseDetail, OrderList, TimelineList } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { readingLabel } from "@/lib/nextDates";
import { apiCasePath, casePath } from "@/lib/refs";
import { timelineDetail } from "@/lib/timeline";

import s from "./case.module.css";
import { OwnershipCard } from "./OwnershipCard";
import { useTimelineLabels } from "./Timeline";

const RECENT = 5;

function PartiesAndActs({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const current = c.parties.filter((p) => p.is_current);
  const advocates = c.advocates.filter((a) => a.is_current);
  const pet = current.find((p) => p.role === "petitioner");
  const res = current.find((p) => p.role === "respondent");
  const advOf = (side: string) =>
    advocates
      .filter((a) => a.side === side)
      .map((a) => a.name_as_listed)
      .join(", ");
  const codes = [...new Set(advocates.map((a) => a.counsel_code).filter((x): x is string => !!x))];
  const acts = c.acts.map((a) => [a.act_name_as_listed, a.section].filter(Boolean).join(", ")).filter(Boolean);
  const shown = (pet ? 1 : 0) + (res ? 1 : 0);
  const more = current.length - shown;
  const items: [string, ReactNode][] = [
    [
      T.case.petitioner,
      <>
        {pet?.name ?? c.parties_as_printed.petitioner_summary ?? "—"}
        {advOf("petitioner") ? <div className="muted">{advOf("petitioner")}</div> : null}
      </>,
    ],
    [
      T.case.respondent,
      <>
        {res?.name ?? c.parties_as_printed.respondent_summary ?? "—"}
        {advOf("respondent") ? <div className="muted">{advOf("respondent")}</div> : null}
      </>,
    ],
  ];
  if (codes.length > 0) items.push([T.case.counselCodes, codes.join("; ")]);
  if (acts.length > 0) items.push([T.case.acts, acts.join("; ")]);
  return (
    <Collapsible summary={T.case.showParties}>
      <KvList items={items} />
      {more > 0 ? <Link href={casePath(caseRef, "parties")}>{T.case.more(more)}</Link> : null}
    </Collapsible>
  );
}

function LatestOrder({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "orders", 1],
    queryFn: () => api<OrderList>(`${apiCasePath(caseRef)}/orders`, { query: { limit: 1 } }),
  });
  const o = list.data?.items[0];
  const reading = o ? readingLabel(o) : null;
  return (
    <section aria-label={T.case.latestOrder}>
      <Card title={T.case.latestOrder} actions={<Link href={casePath(caseRef, "orders")}>{T.case.allOrders}</Link>}>
        <div className="stack">
          {list.isPending ? <Loading lines={2} /> : null}
          <ErrorBanner error={list.error} />
          {list.data && !o ? <p className="muted">{T.case.noOrders}</p> : null}
          {o ? (
            <>
              <div>
                <strong>{formatDate(o.order_date)}</strong> · {o.kind}
              </div>
              {o.order_details ? <p className={s.orderText}>{o.order_details}</p> : null}
              <OrderRow caseRef={caseRef} order={o} label={T.case.showOrder} />
            </>
          ) : null}
          {reading ? (
            <div>
              {reading.date ? T.nd.foundInOrder(reading.date) : `${T.nd.readCol}: ${reading.words}`}
              {reading.date && o?.next_date_status === "period" ? <span className="muted"> · {reading.words}</span> : null}
            </div>
          ) : null}
          <section className="stack" aria-label={T.nd.card}>
            <NextDateBlock caseRef={caseRef} c={c} />
          </section>
          <PartiesAndActs caseRef={caseRef} c={c} />
        </div>
      </Card>
    </section>
  );
}

function RecentActivity({ caseRef }: { caseRef: string }) {
  const labels = useTimelineLabels();
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "timeline", "recent"],
    queryFn: () => api<TimelineList>(`${apiCasePath(caseRef)}/timeline`, { query: { limit: RECENT, offset: 0 } }),
  });
  return (
    <section aria-label={T.case.recentActivity}>
      <Card title={T.case.recentActivity} actions={<Link href={casePath(caseRef, "timeline")}>{T.case.timelineLink}</Link>}>
        {list.isPending ? <Loading lines={3} /> : null}
        <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
        {list.data ? (
          list.data.items.length === 0 ? (
            <p className="muted">{T.case.noTimeline}</p>
          ) : (
            <ol className={s.rail} aria-label={T.case.recentActivity}>
              {list.data.items.slice(0, RECENT).map((e, i) => {
                const detail = timelineDetail(e.type, e.payload, labels);
                return (
                  <li key={`${e.occurred_at}-${i}`} className={s.railItem}>
                    <div className={s.when}>{formatDateTime(e.occurred_at)}</div>
                    <strong>{e.label}</strong>
                    {detail || e.actor_name ? (
                      <div className="muted">{[detail, e.actor_name].filter(Boolean).join(" · ")}</div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          )
        ) : null}
      </Card>
    </section>
  );
}

export function Overview({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const c = query.data;
  const basis = c.access_basis.map((b) => T.case.bases[b] ?? b).join(", ");
  return (
    <div className="stack">
      <div className={s.caseGrid}>
        <LatestOrder caseRef={caseRef} c={c} />
        <RecentActivity caseRef={caseRef} />
      </div>
      <Collapsible summary={T.case.ownershipFolded}>
        <OwnershipCard caseRef={caseRef} detail={c} secondaryOnly />
      </Collapsible>
      {basis ? <p className="muted">{T.case.seenAs(basis)}</p> : null}
    </div>
  );
}
