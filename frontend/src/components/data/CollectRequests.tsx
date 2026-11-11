"use client";

/**
 * Collect Now's requests with their live progress (design data-collection-redesign, decisions 23, 30-32; round 3):
 * the Requests card (each request's bar, counts and state, Show Items in a side panel, Stop Using Everything for a
 * bulk request), the watched request's progress panel, the "use everything" panel and the collector's note. Polling
 * only while the tab is visible: a watched request every 2 s, the list every 5 s while any request runs, else 30 s.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import {
  Badge,
  Button,
  CollectProgress,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  Pagination,
  ProgressBar,
  ScrollBox,
  SidePanel,
  StatusDot,
  type CollectStepState,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { can } from "@/lib/can";
import {
  DC_KEYS,
  REQUEST_POLL,
  failedWhat,
  requestCounts,
  requestLeft,
  requestSegments,
  requestWhat,
  type CollectPlan,
  type CollectRequest,
  type CollectRequests,
  type CollectSummary,
} from "@/lib/dataCollection";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { COLLECT_ERRORS, T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { labelFor } from "@/lib/displayLabels";

import ds from "./data.module.css";

const ITEMS_PAGE = 100;

/** The requests of the last 7 days: every 5 s while one runs, every 30 s otherwise (decision 32). */
export function useRequests(enabled = true) {
  return useQuery({
    queryKey: DC_KEYS.requests,
    enabled,
    queryFn: () => api<CollectRequests>("/admin/data-load/requests"),
    refetchInterval: (q) => ((q.state.data?.active ?? 0) > 0 ? REQUEST_POLL.active : REQUEST_POLL.idle),
    refetchIntervalInBackground: false,
  });
}

/** One request, watched every 2 s until it has finished. */
export function useRequest(id: string | null, offset = 0) {
  return useQuery({
    queryKey: [...DC_KEYS.request(id ?? ""), offset],
    queryFn: () => api<CollectRequest>(`/admin/data-load/requests/${id}?limit=${ITEMS_PAGE}&offset=${offset}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && q.state.data.finished ? false : REQUEST_POLL.watched),
    refetchIntervalInBackground: false,
  });
}

const n = (value: number | null | undefined) => formatNumber(value ?? 0);

/** "Waiting for the collector to start" and "the court's hourly limit is used up" (decisions 23-24). */
export function CollectorNotes({ data }: { data: Pick<CollectRequest, "collector" | "window" | "finished"> }) {
  if (data.finished) return null;
  return (
    <>
      {data.collector.not_running ? (
        <Notice tone="warning">
          {data.collector.last_active_at
            ? T.dc.collectorWaitingNote(formatTime(data.collector.last_active_at))
            : T.dc.collectorNeverNote}
        </Notice>
      ) : null}
      {data.window.limit_used_up ? (
        <Notice tone="warning">{T.dc.limitUsedNote(formatTime(data.window.resumes_at ?? data.window.next_reset_at))}</Notice>
      ) : null}
    </>
  );
}

/** The progress panel of one request (decision 25): the steps, then nothing more until it has finished. */
export function RequestProgress({ data }: { data: CollectRequest }) {
  const hasDetails = (data.by_kind.dossier ? Object.values(data.by_kind.dossier).reduce((a, b) => a + b, 0) : 0) > 0;
  const steps = data.steps;
  const details: CollectStepState | null = hasDetails ? detailsState(steps.details) : data.results.length ? "done" : null;
  if (data.kind === "cases" || data.kind === "details" || data.kind === "refetch_case") {
    return (
      <div className="stack">
        <CollectProgress details={details} orders={data.results.length ? steps.orders : null} etaSeconds={data.eta_seconds} />
        <CollectorNotes data={data} />
      </div>
    );
  }
  return (
    <div className="stack">
      <ProgressBar
        segments={requestSegments(data.counts)}
        max={data.total}
        label={requestWhat(data)}
        text={requestCounts(data.counts, data.total)}
      />
      <CollectorNotes data={data} />
    </div>
  );
}

/** The case details step of a request in one word: fetching while any is, then waiting, then done. */
export function detailsState(c: Record<string, number>): CollectStepState {
  if (c.fetching) return "fetching";
  if (c.waiting) return "waiting";
  if (c.failed && !c.done) return "failed";
  if (c.not_found && !c.done) return "not_found";
  return "done";
}

/** The result of a finished request of a few cases (decision 25): number, CNR, status, details, order PDFs, retry. */
export function RequestResult({ data }: { data: CollectRequest }) {
  if (!data.results.length) return null;
  return (
    <ul className={ds.results} aria-label={T.dc.resultTitle}>
      {data.results.map((r) => (
        <li key={r.case.id} className={ds.result}>
          <p>
            <b className="mono">{r.case.case_no_text ?? r.case.ref_no}</b> <span className="mono muted">{r.case.cnr ?? ""}</span>{" "}
            {r.status ? <Badge>{r.status}</Badge> : null}
          </p>
          <p className="muted">
            {r.details_fetched_at ? T.dc.resultDetailsAt(formatDateTime(r.details_fetched_at)) : T.dc.resultNoDetails}
          </p>
          <p>{T.dc.resultOrders(r.orders.stored, r.orders.not_available)}</p>
          {r.orders.retry_at ? (
            <p className="muted">{T.dc.resultRetry(Math.max(1, r.orders.failed + r.orders.waiting), formatTime(r.orders.retry_at))}</p>
          ) : null}
          <p>
            <Link href={casePath(r.case.ref_no)}>{T.dc.openCaseButton}</Link>
          </p>
        </li>
      ))}
    </ul>
  );
}

/** The "use everything" panel (decision 30): what others experience while the request runs, and the estimate. */
export function UseEverything({ plan }: { plan: CollectPlan }) {
  const calls = n(plan.calls);
  const split =
    plan.this_hour !== null && plan.after_reset && plan.next_reset_at
      ? T.dc.useSplit(calls, n(plan.this_hour), formatTime(plan.next_reset_at))
      : T.dc.useCalls(calls);
  return (
    <div className={ds.useEverything} role="note" aria-label={T.dc.useTitle}>
      <p className={ds.useTitle}>{T.dc.useTitle}</p>
      <p>{T.dc.useIntro}</p>
      <ul>
        <li>{T.dc.useOthers(plan.search_floor)}</li>
        <li>{T.dc.useDaily}</li>
        <li>{T.dc.useSafe}</li>
      </ul>
      <p>
        {split}
        {plan.finish_at ? ` ${T.dc.useFinish(formatTime(plan.finish_at))}` : ""}
      </p>
    </div>
  );
}

/** The Requests card (decision 32), first on the tab when a request ran in the last 7 days. */
export function RequestsCard({ query }: { query: ReturnType<typeof useRequests> }) {
  const me = useMe();
  const qc = useQueryClient();
  const [open, setOpen] = useState<CollectSummary | null>(null);
  const [stopping, setStopping] = useState<CollectSummary | null>(null);
  const [stopped, setStopped] = useState<string | null>(null);
  const stop = useAction();
  const items = query.data?.items ?? [];
  if (query.isPending) return <Loading />;
  if (!items.length && !query.error) return null;
  async function confirmStop() {
    if (!stopping) return;
    const out = await stop.run(() =>
      api<{ request_id: string; moved: number }>(`/admin/data-load/requests/${stopping.request_id}/stop`, { method: "POST" }),
    );
    if (out.ok) {
      setStopped(T.dc.stoppedNote(out.value.moved));
      setStopping(null);
    }
    await qc.invalidateQueries({ queryKey: DC_KEYS.all });
  }
  return (
    <section className={ds.panel} aria-labelledby="dc-requests">
      <div className="stack">
        <h2 id="dc-requests">{T.dc.requestsTitle}</h2>
        <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
        {stopped ? <Notice>{stopped}</Notice> : null}
        {items.length ? (
          <ScrollBox label={T.dc.requestListLabel}>
            <DataTable
              caption={T.dc.requestsTitle}
              rows={items}
              rowKey={(r) => r.request_id}
              columns={[
                { key: "what", header: T.dc.reqCols.what, primary: true, cell: (r) => requestWhat(r) },
                {
                  key: "who",
                  header: T.dc.reqCols.askedBy,
                  cell: (r) => (
                    <>
                      {r.asked_by ?? "—"}
                      <br />
                      <span className="muted">{formatDateTime(r.asked_at)}</span>
                    </>
                  ),
                },
                {
                  key: "progress",
                  header: T.dc.reqCols.progress,
                  cell: (r) => (
                    <ProgressBar
                      size="sm"
                      segments={requestSegments(r.counts)}
                      max={r.total}
                      label={requestWhat(r)}
                      text={requestCounts(r.counts, r.total)}
                    />
                  ),
                },
                { key: "state", header: T.dc.reqCols.state, cell: (r) => <RequestState r={r} /> },
                {
                  key: "actions",
                  header: <span className="visually-hidden">{T.dc.showItemsButton}</span>,
                  label: T.dc.showItemsButton,
                  // the buttons name themselves: the card's full width (design portal-ui-kit-fixes, build deviations)
                  actions: true,
                  cell: (r) => (
                    <span className={ds.rowActions}>
                      <Button variant="secondary" size="sm" onClick={() => setOpen(r)}>
                        {T.dc.showItemsButton}
                      </Button>
                      {r.using_everything && can(me.data, "admin.data_load") ? (
                        <Button variant="secondary" size="sm" onClick={() => setStopping(r)}>
                          {T.dc.stopButton}
                        </Button>
                      ) : null}
                    </span>
                  ),
                },
              ]}
            />
          </ScrollBox>
        ) : (
          <EmptyState>{T.dc.requestsEmpty}</EmptyState>
        )}
      </div>
      <ConfirmDialog
        open={stopping !== null}
        title={T.dc.stopTitle}
        onClose={() => setStopping(null)}
        onConfirm={() => void confirmStop()}
        busy={stop.busy}
        error={stop.error}
        messages={COLLECT_ERRORS}
        confirmLabel={T.dc.stopButton}
        danger
      >
        <p>{stopping ? T.dc.stopBody(requestLeft(stopping.counts)) : null}</p>
      </ConfirmDialog>
      {open ? <ItemsPanel summary={open} onClose={() => setOpen(null)} /> : null}
    </section>
  );
}

function RequestState({ r }: { r: CollectSummary }) {
  if (r.stopped) return <Badge tone="warning">{T.dc.stoppedBadge}</Badge>;
  if (r.using_everything)
    return (
      <span className={ds.inlineState}>
        <StatusDot tone="busy" pulse />
        <span className={ds.pulse}>{T.dc.usingBadge}</span>
        {r.expected_end ? <span className="muted">{formatTime(r.expected_end)}</span> : null}
      </span>
    );
  if (r.finished) return <Badge tone="success">{T.dc.finishedBadge}</Badge>;
  return (
    <span className={ds.inlineState}>
      <StatusDot tone="busy" pulse />
      <span className={ds.pulse}>{T.dc.runningBadge}</span>
    </span>
  );
}

/** Show Items (decision 32): the request's items paged by 100 in a side panel, each with its state in words. */
function ItemsPanel({ summary, onClose }: { summary: CollectSummary; onClose: () => void }) {
  const [offset, setOffset] = useState(0);
  const q = useRequest(summary.request_id, offset);
  const what = requestWhat(summary);
  return (
    <SidePanel open title={T.dc.itemsTitle(what)} onClose={onClose} wide>
      <div className="stack">
        <ErrorBanner error={q.error} onRetry={() => q.refetch()} messages={COLLECT_ERRORS} />
        {q.isPending ? <Loading /> : null}
        {q.data ? (
          <>
            <RequestProgress data={q.data} />
            {q.data.finished ? <RequestResult data={q.data} /> : null}
            <DataTable
              caption={T.dc.itemsTitle(what)}
              rows={q.data.items}
              rowKey={(i) => `${i.kind}:${i.ref}`}
              columns={[
                { key: "what", header: T.dc.itemCols.what, primary: true, cell: (i) => <span title={i.ref}>{failedWhat(i.kind, i.ref)}</span> },
                { key: "kind", header: T.dc.itemCols.kind, cell: (i) => labelFor(T.dc.kinds, i.kind) },
                {
                  key: "state",
                  header: T.dc.itemCols.state,
                  cell: (i) => (
                    <>
                      <span className={i.state === "fetching" ? ds.pulse : undefined}>{labelFor(T.kit.collect.states, i.state)}</span>
                      {i.state === "waiting_retry" && i.not_before ? (
                        <>
                          <br />
                          <span className="muted">{T.dc.retryAtNote(formatTime(i.not_before))}</span>
                        </>
                      ) : null}
                    </>
                  ),
                },
                { key: "tries", header: T.dc.itemCols.tries, align: "right", cell: (i) => n(i.attempts) },
                { key: "problem", header: T.dc.itemCols.problem, cell: (i) => i.problem ?? "—" },
              ]}
              empty={<EmptyState>{T.dc.requestsEmpty}</EmptyState>}
            />
            <Pagination offset={offset} limit={ITEMS_PAGE} total={q.data.total} onChange={setOffset} />
          </>
        ) : null}
      </div>
    </SidePanel>
  );
}
