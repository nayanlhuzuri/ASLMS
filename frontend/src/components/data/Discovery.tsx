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
  DataTable,
  Kpi,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DiscoverySummary, DiscoverySweep } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

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
    <section className={`stack ${ds.panel}`} aria-label={T.discovery.dataTab}>
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
          <div className={ds.kpis}>
            <Kpi label={T.discovery.termsActive} value={data.data.terms.active} />
            <Kpi label={T.discovery.termsInactive} value={data.data.terms.inactive} />
            <Kpi label={T.discovery.casesFoundAll} value={data.data.cases.found} />
            <Kpi label={T.discovery.createdByDiscovery} value={data.data.cases.created_by_discovery} />
            <Kpi label={T.discovery.recommendedFromDiscovery} value={data.data.cases.recommended_from_discovery} />
          </div>
          <p>
            {data.data.last_searched_at
              ? T.discovery.lastSearchedAt(formatDateTime(data.data.last_searched_at))
              : T.discovery.neverSearched}
          </p>
          <DataTable
            caption={T.discovery.queue}
            rows={[...KINDS]}
            rowKey={(k) => k}
            columns={[
              { key: "kind", header: T.data.kind, primary: true, cell: (k) => T.data.kinds[k] ?? k },
              { key: "pending", header: T.data.pending, align: "right", cell: (k) => formatNumber(data.data.queue.by_kind[k].pending) },
              { key: "waiting", header: T.data.waiting, align: "right", cell: (k) => formatNumber(data.data.queue.by_kind[k].waiting) },
              { key: "running", header: T.data.runningCol, align: "right", cell: (k) => formatNumber(data.data.queue.by_kind[k].running) },
              { key: "failed", header: T.data.failed, align: "right", cell: (k) => formatNumber(data.data.queue.by_kind[k].failed) },
            ]}
          />
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
            <DataTable
              caption={T.discovery.failures}
              rows={data.data.latest_failures}
              rowKey={(f) => `${f.kind}:${f.ref}`}
              columns={[
                { key: "kind", header: T.data.kind, cell: (f) => T.data.kinds[f.kind] ?? f.kind },
                { key: "ref", header: T.data.ref, primary: true, cell: (f) => <span className="mono">{f.ref}</span> },
                { key: "error", header: T.data.lastError, cell: (f) => f.last_error ?? "—" },
                { key: "at", header: T.discovery.finishedAt, cell: (f) => formatDateTime(f.finished_at) },
              ]}
            />
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
