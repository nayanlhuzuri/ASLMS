"use client";

/**
 * Discovery (design department-discovery, decision 13d; owner's decisions of 14 Oct 2026), a Data collection tab for
 * the data readers: the discovery share of each quota window and the calls it used, the discovery-lane queue by kind,
 * the names searched, the cases found and created by discovery, the latest failures, and "Sweep every name now" for
 * `admin.data_load`. These are the only screens that show discovery's call counts. System figures only, no case data.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  numCell,
  Table,
  Tile,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DiscoverySummary, DiscoverySweep } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

const KEY = ["data-discovery"] as const;
const KINDS = ["party_search", "dossier", "order_pdf"] as const;
const PROBE_MINUTES = 3;

export function Discovery() {
  const me = useMe();
  const queryClient = useQueryClient();
  const action = useAction();
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const data = useQuery({ queryKey: KEY, queryFn: () => api<DiscoverySummary>("/admin/discovery") });

  async function sweep() {
    const out = await action.run(() => api<DiscoverySweep>("/admin/discovery/sweep", { method: "POST", body: {} }));
    if (out.ok) {
      setConfirm(false);
      setMessage(T.discovery.swept(out.value.rows_queued, out.value.terms));
      await queryClient.invalidateQueries({ queryKey: KEY });
    }
  }

  return (
    <section className="stack" aria-label={T.discovery.dataTab}>
      <h2>{T.discovery.dataTab}</h2>
      {data.isPending ? <Loading /> : null}
      <ErrorBanner error={data.error} onRetry={() => data.refetch()} />
      {message ? <Notice>{message}</Notice> : null}
      {data.data ? (
        <>
          <section className="stack" aria-label={T.discovery.share}>
            <h3>{T.discovery.share}</h3>
            <p>
              {data.data.settings.share === 0
                ? T.discovery.shareOff
                : T.discovery.shareLine(
                    formatNumber(data.data.window.discovery_calls),
                    formatNumber(data.data.settings.share),
                    formatNumber(data.data.window.share_left),
                  )}
            </p>
            <p className="muted">
              {T.data.windowLine(
                data.data.window.status,
                formatTime(data.data.window.started_at),
                formatTime(data.data.window.next_reset_at),
                PROBE_MINUTES,
              )}
            </p>
            <p className="muted">{T.discovery.fromYear(data.data.settings.from_year)}</p>
          </section>
          <div className="row">
            <Tile label={T.discovery.termsActive} value={data.data.terms.active} />
            <Tile label={T.discovery.termsInactive} value={data.data.terms.inactive} />
            <Tile label={T.discovery.casesFoundAll} value={data.data.cases.found} />
            <Tile label={T.discovery.createdByDiscovery} value={data.data.cases.created_by_discovery} />
            <Tile label={T.discovery.recommendedFromDiscovery} value={data.data.cases.recommended_from_discovery} />
          </div>
          <p>
            {data.data.last_searched_at
              ? T.discovery.lastSearchedAt(formatDateTime(data.data.last_searched_at))
              : T.discovery.neverSearched}
          </p>
          <Table caption={T.discovery.queue}>
            <thead>
              <tr>
                <th scope="col">{T.data.kind}</th>
                <th scope="col" className={numCell}>
                  {T.data.pending}
                </th>
                <th scope="col" className={numCell}>
                  {T.data.waiting}
                </th>
                <th scope="col" className={numCell}>
                  {T.data.runningCol}
                </th>
                <th scope="col" className={numCell}>
                  {T.data.failed}
                </th>
              </tr>
            </thead>
            <tbody>
              {KINDS.map((k) => {
                const row = data.data.queue.by_kind[k];
                return (
                  <tr key={k}>
                    <td>{T.data.kinds[k] ?? k}</td>
                    <td className={numCell}>{formatNumber(row.pending)}</td>
                    <td className={numCell}>{formatNumber(row.waiting)}</td>
                    <td className={numCell}>{formatNumber(row.running)}</td>
                    <td className={numCell}>{formatNumber(row.failed)}</td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {can(me.data, "admin.data_load") ? (
            <div className="row">
              <Button variant="secondary" onClick={() => setConfirm(true)}>
                {T.discovery.sweepAll}
              </Button>
            </div>
          ) : null}
          <h3>{T.discovery.failures}</h3>
          {data.data.latest_failures.length === 0 ? (
            <EmptyState>{T.discovery.noFailures}</EmptyState>
          ) : (
            <Table caption={T.discovery.failures}>
              <thead>
                <tr>
                  <th scope="col">{T.data.kind}</th>
                  <th scope="col">{T.data.ref}</th>
                  <th scope="col">{T.data.lastError}</th>
                  <th scope="col">{T.discovery.finishedAt}</th>
                </tr>
              </thead>
              <tbody>
                {data.data.latest_failures.map((f) => (
                  <tr key={`${f.kind}:${f.ref}`}>
                    <td>{T.data.kinds[f.kind] ?? f.kind}</td>
                    <td className="mono">{f.ref}</td>
                    <td>{f.last_error ?? "—"}</td>
                    <td>{formatDateTime(f.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </>
      ) : null}
      {confirm ? (
        <ConfirmDialog
          open
          title={T.discovery.sweepTitle}
          onClose={() => setConfirm(false)}
          onConfirm={() => void sweep()}
          busy={action.busy}
          error={action.error}
          confirmLabel={T.discovery.sweepAll}
        >
          <p>{T.discovery.sweepText}</p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
