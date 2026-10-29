"use client";

/**
 * System Health's Court Calls section (design data-collection-redesign, decision 3), shown with `admin.service_health`
 * and a health-reader function (`showsCourtCalls`), because its data comes from the court-health endpoints with their
 * own guards: the recent quota resets (`GET /admin/napix/health`), the e-mail waiting and failed (`GET
 * /admin/data-health`) and today's court call log (`GET /admin/napix/calls`, with More) in its own scrolling box. The
 * person who caused a call is shown only where the API returns it (the court operators). No call is made to the court.
 */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { Button, Card, DataTable, EmptyState, ErrorBanner, KvList, Loading, ScrollBox } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CallList, DataHealth, NapixHealth } from "@/lib/api/types";
import { courtServiceName, familyWords } from "@/lib/dataCollection";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./system.module.css";

const LIMIT = 50;
type Call = CallList["items"][number];

export function CourtCalls() {
  const napix = useQuery({ queryKey: ["data-health", "napix"], queryFn: () => api<NapixHealth>("/admin/napix/health") });
  const snapshot = useQuery({ queryKey: ["data-health"], queryFn: () => api<DataHealth>("/admin/data-health") });
  return (
    <section className="stack" id="calls" aria-labelledby="calls-heading">
      <div className={s.sectionHead}>
        <h2 id="calls-heading">{T.system.callsTitle}</h2>
        <span className="muted">{T.system.callsIntro}</span>
      </div>
      <div className={s.callsGrid}>
        <Card title={T.system.resetsTitle}>
          <ErrorBanner error={napix.error} onRetry={() => void napix.refetch()} />
          {napix.isPending ? <Loading lines={2} /> : null}
          {napix.data ? (
            <DataTable
              caption={T.system.resetsTitle}
              rows={napix.data.window.recent_resets}
              rowKey={(r) => r.observed_at}
              empty={<EmptyState>{T.system.resetsNone}</EmptyState>}
              columns={[
                { key: "time", header: T.system.resetCols.time, primary: true, cell: (r) => formatTime(r.observed_at) },
                { key: "before", header: T.system.resetCols.before, align: "right", cell: (r) => formatNumber(r.previous_remaining) },
                { key: "after", header: T.system.resetCols.after, align: "right", cell: (r) => formatNumber(r.remaining) },
                {
                  key: "timing",
                  header: T.system.resetCols.timing,
                  cell: (r) => (r.precise ? T.system.timing.exact : T.system.timing.estimated),
                },
              ]}
            />
          ) : null}
        </Card>
        <Card title={T.system.mailTitle}>
          <ErrorBanner error={snapshot.error} onRetry={() => void snapshot.refetch()} />
          {snapshot.isPending ? <Loading lines={2} /> : null}
          {snapshot.data ? (
            <KvList
              items={[
                [T.system.mailWaiting, formatNumber(snapshot.data.mail.email_queued)],
                [T.system.mailFailed, formatNumber(snapshot.data.mail.email_failed)],
              ]}
            />
          ) : null}
        </Card>
      </div>
      <CallLog />
    </section>
  );
}

function CallLog() {
  const calls = useInfiniteQuery({
    queryKey: ["system-health", "calls"],
    queryFn: ({ pageParam }) => api<CallList>("/admin/napix/calls", { query: { cursor: pageParam, limit: LIMIT } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = calls.data?.pages.flatMap((p) => p.items) ?? [];
  const showPeople = items.some((c) => c.user_name);
  return (
    <Card title={T.system.callLogTitle}>
      <div className="stack">
        <ErrorBanner error={calls.error} onRetry={() => void calls.refetch()} />
        {calls.isPending ? <Loading /> : null}
        {calls.data ? (
          items.length === 0 ? (
            <EmptyState>{T.system.callLogNone}</EmptyState>
          ) : (
            <ScrollBox label={T.system.callLogTitle}>
              <DataTable
                caption={T.system.callLogTitle}
                rows={items}
                rowKey={(c) => c.id}
                columns={[
                  { key: "when", header: T.system.callCols.when, cell: (c) => formatDateTime(c.called_at) },
                  {
                    key: "service",
                    header: T.system.callCols.service,
                    primary: true,
                    cell: (c) => <span title={c.api}>{courtServiceName(c.api)}</span>,
                  },
                  {
                    key: "lane",
                    header: T.system.callCols.kindOfWork,
                    cell: (c) => T.dc.lanes[c.lane ?? "outside_queue"] ?? c.lane,
                  },
                  { key: "result", header: T.system.callCols.result, cell: (c) => resultWords(c) },
                  {
                    key: "left",
                    header: T.system.callCols.left,
                    align: "right",
                    cell: (c) => (c.rate_limit_remaining === null || c.rate_limit_remaining === undefined ? "—" : formatNumber(c.rate_limit_remaining)),
                  },
                  ...(showPeople ? [{ key: "person", header: T.system.callCols.person, cell: (c: Call) => c.user_name ?? "—" }] : []),
                ]}
              />
            </ScrollBox>
          )
        ) : null}
        {calls.hasNextPage ? (
          <div>
            <Button variant="secondary" busy={calls.isFetchingNextPage} onClick={() => void calls.fetchNextPage()}>
              {T.system.more}
            </Button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function resultWords(c: Call): string {
  if (c.ok) return T.system.callResult.ok;
  return T.system.callFailed(familyWords(c.error_family ?? (c.http_status ? `HTTP ${c.http_status}` : null)));
}
