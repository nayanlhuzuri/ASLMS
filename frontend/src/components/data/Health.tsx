"use client";

/**
 * The data-health tab (design audit-screens, decisions 5-11; data-load-console, decisions 12 and 19): the snapshot of
 * `GET /admin/data-health` and `GET /admin/napix/health`, refreshed every minute, and the buttons. The court gateway
 * block shows the detected quota window, its recent resets and, for the NAPIX operators only (the API sends `by_user`
 * to them alone), the calls by user (design napix-window). Sync masters needs
 * `admin.masters_sync`; the re-fetch buttons `admin.napix_refetch` and warn before queuing data already held ("Fetch
 * anyway" resends with `force`); the connectivity check either function. No GET calls NAPIX. The document text
 * block (design document-ocr, decision 4) counts documents by text status, the ones not read split into scanned PDFs,
 * images and old Word files. Design court-data-freshness, decision 17: the daily cycle shows the lists corrected and
 * the state of the date's recheck; the Retention block shows the call-log rule, its last purge, the two tables' sizes
 * and the monthly refresh of disposed cases.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, DataTable, ErrorBanner, Kpi, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DataHealth, HealthCheck, NapixHealth } from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

export const HEALTH_POLL_MS = 60_000;

export function Health() {
  const me = useMe();
  const snapshot = useQuery({
    queryKey: ["data-health"],
    queryFn: () => api<DataHealth>("/admin/data-health"),
    refetchInterval: HEALTH_POLL_MS,
  });
  const napix = useQuery({
    queryKey: ["data-health", "napix"],
    queryFn: () => api<NapixHealth>("/admin/napix/health"),
    refetchInterval: HEALTH_POLL_MS,
  });
  const checker = canAny(me.data, ["admin.napix_refetch", "admin.masters_sync"]);
  return (
    <section className={ds.board} aria-label={T.data.health}>
      {can(me.data, "reports.state") ? (
        // design portal-reports, decision 10: the dated report of the same figures
        <p className={ds.wide}>
          <Link href="/reports/data-health">{T.reports.periodReport}</Link>
        </p>
      ) : null}
      {snapshot.error || napix.error ? (
        <div className={ds.wide}>
          <ErrorBanner error={snapshot.error ?? napix.error} onRetry={() => (snapshot.refetch(), napix.refetch())} />
        </div>
      ) : null}
      {snapshot.isPending || napix.isPending ? (
        <div className={ds.wide}>
          <Loading lines={6} />
        </div>
      ) : null}
      {napix.data ? <NapixBlock data={napix.data} /> : null}
      {snapshot.data ? <SnapshotBlocks data={snapshot.data} /> : null}
      {checker ? <Buttons /> : null}
    </section>
  );
}

function NapixBlock({ data }: { data: NapixHealth }) {
  const w = data.window;
  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.napix}>
      <h2>{T.data.napix}</h2>
      <p>
        {data.enabled ? <Badge tone="success">{T.data.switchApi(true)}</Badge> : <Badge tone="warning">{T.data.switchApi(false)}</Badge>}{" "}
        <span className="muted">{T.data.switchNote}</span>
      </p>
      <div className={ds.kpis}>
        <Kpi
          label={T.data.window}
          value={w.calls}
          sub={`${formatNumber(w.failed)} ${T.data.failed.toLowerCase()}`}
          tone={w.failed > 0 ? "danger" : undefined}
        />
        <Kpi
          label={T.data.today}
          value={data.today.calls}
          sub={`${formatNumber(data.today.failed)} ${T.data.failed.toLowerCase()}`}
          tone={data.today.failed > 0 ? "danger" : undefined}
        />
      </div>
      <p>{T.data.windowLine(w.status, formatTime(w.started_at), formatTime(w.next_reset_at), Math.round(w.probe_seconds / 60))}</p>
      <p>{w.remaining === null || w.remaining === undefined ? T.data.remainingUnknown : T.data.remaining(formatNumber(w.remaining))}</p>
      <p className="muted">
        {T.data.lastCall}: {formatDateTime(data.last_call_at)}. {T.data.lastCheck}:{" "}
        {data.last_check ? `${formatDateTime(data.last_check.called_at)} (${data.last_check.ok ? T.data.ok : data.last_check.error_family ?? "—"})` : "—"}
      </p>
      {w.recent_resets.length > 0 ? (
        <section className="stack" aria-label={T.data.recentResets}>
          <h3>{T.data.recentResets}</h3>
          <ul>
            {w.recent_resets.map((r) => (
              <li key={r.observed_at}>
                {T.data.resetRow(formatTime(r.observed_at), r.previous_remaining, r.remaining)}
                {r.precise ? (
                  <>
                    {" "}
                    <Badge tone="success">{T.data.precise}</Badge>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data.by_user ? <CallsByUser byUser={data.by_user} /> : null}
    </section>
  );
}

type ByUser = NonNullable<NapixHealth["by_user"]>;

function CallsByUser({ byUser }: { byUser: ByUser }) {
  const ids = Array.from(new Set([...byUser.window, ...byUser.today].map((u) => u.user_id)));
  const names = new Map([...byUser.today, ...byUser.window].map((u) => [u.user_id, u.name]));
  const find = (list: ByUser["window"], id: string) => list.find((u) => u.user_id === id);
  return (
    <section className="stack" aria-label={T.data.byUser}>
      <h3>{T.data.byUser}</h3>
      {ids.length === 0 ? (
        <p className="muted">{T.data.noUserCalls}</p>
      ) : (
        <DataTable
          caption={T.data.byUser}
          rows={ids}
          rowKey={(id) => id}
          columns={[
            { key: "user", header: T.data.user, primary: true, cell: (id) => names.get(id) },
            { key: "window", header: T.data.window, align: "right", cell: (id) => formatNumber(find(byUser.window, id)?.calls ?? 0) },
            { key: "today", header: T.data.today, align: "right", cell: (id) => formatNumber(find(byUser.today, id)?.calls ?? 0) },
            { key: "failed", header: T.data.failed, align: "right", cell: (id) => formatNumber(find(byUser.today, id)?.failed ?? 0) },
          ]}
        />
      )}
    </section>
  );
}

function SnapshotBlocks({ data }: { data: DataHealth }) {
  return (
    <>
      <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.queue}>
        <h2>{T.data.queue}</h2>
        <DataTable
          caption={T.data.queue}
          rows={data.queue.by_kind}
          rowKey={(k) => k.kind}
          columns={[
            { key: "kind", header: T.data.kind, primary: true, cell: (k) => T.data.kinds[k.kind] ?? k.kind },
            { key: "pending", header: T.data.pending, align: "right", cell: (k) => formatNumber(k.pending) },
            { key: "load", header: T.data.lanes.load, align: "right", cell: (k) => formatNumber(k.by_lane.load) },
            { key: "discovery", header: T.data.lanes.discovery, align: "right", cell: (k) => formatNumber(k.by_lane.discovery) },
            { key: "daily", header: T.data.lanes.daily, align: "right", cell: (k) => formatNumber(k.by_lane.daily) },
            { key: "request", header: T.data.lanes.request, align: "right", cell: (k) => formatNumber(k.by_lane.request) },
            { key: "running", header: T.data.runningCol, align: "right", cell: (k) => formatNumber(k.running) },
            { key: "failed", header: T.data.failed, align: "right", cell: (k) => formatNumber(k.failed) },
          ]}
        />
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.dailyCycle}>
        <h2>{T.data.dailyCycle}</h2>
        <DataTable
          caption={T.data.dailyCycle}
          rows={data.daily_cycle}
          rowKey={(d) => d.date}
          columns={[
            { key: "date", header: T.data.date, primary: true, cell: (d) => formatDate(d.date) },
            { key: "status", header: T.data.status, width: "var(--lead-w)", cell: (d) => d.causelist_day?.status ?? "—" },
            { key: "lists", header: T.data.lists, align: "right", cell: (d) => formatNumber(d.lists_stored) },
            { key: "entries", header: T.data.entries, align: "right", cell: (d) => formatNumber(d.entries_parsed) },
            { key: "corrected", header: T.data.listsCorrected, align: "right", cell: (d) => formatNumber(d.lists_corrected ?? 0) },
            {
              key: "recheck",
              header: T.data.recheck,
              cell: (d) =>
                d.recheck
                  ? `${d.recheck.status}${d.recheck.called !== null && d.recheck.called !== undefined ? ` · ${T.data.recheckCalled(d.recheck.called)}` : ""}`
                  : "—",
            },
          ]}
        />
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.masters}>
        <h2>{T.data.masters}</h2>
        <ul>
          {data.masters.map((m) => (
            <li key={m.master}>
              {m.master}: {formatDateTime(m.fetched_at)} ({formatNumber(m.row_count)})
            </li>
          ))}
        </ul>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.jobs}>
        <h2>{T.data.jobs}</h2>
        <ul>
          {data.jobs.map((j) => (
            <li key={j.job}>
              <span className="mono">{j.job}</span>: {j.status}, {formatDateTime(j.started_at)}
            </li>
          ))}
        </ul>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.mail}>
        <h2>{T.data.mail}</h2>
        <p>
          {formatNumber(data.mail.email_queued)} / {formatNumber(data.mail.email_failed)}
        </p>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.openFailures}>
        <h2>{T.data.openFailures}</h2>
        <ul>
          {data.failures.map((f) => (
            <li key={f.kind}>
              <span className="mono">{f.kind}</span>: {formatNumber(f.open)}
            </li>
          ))}
        </ul>
      </section>
      <DocumentsTextBlock data={data.documents_text} />
      {data.retention ? <RetentionBlock data={data.retention} /> : null}
    </>
  );
}

/** Design court-data-freshness, decisions 6, 19 and 21: the NAPIX logs kept and the monthly refresh of disposed cases. */
function RetentionBlock({ data }: { data: NonNullable<DataHealth["retention"]> }) {
  const mb = (bytes: number) => T.data.megabytes(formatNumber(Math.round(bytes / 1_048_576)));
  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.retention}>
      <h2>{T.data.retention}</h2>
      <ul>
        <li>{T.data.callLogKept(data.call_log_keep_days, formatDateTime(data.call_log_oldest_at))}</li>
        <li>
          {data.last_purge_at
            ? T.data.lastPurge(formatDateTime(data.last_purge_at), formatNumber(data.last_purge_deleted ?? 0), data.last_purge_status ?? "—")
            : T.data.noPurgeYet}
        </li>
        <li>{T.data.tableSizes(mb(data.call_log_bytes), mb(data.responses_bytes))}</li>
        <li>
          {T.data.disposedRefresh(
            formatNumber(data.disposed_refresh.eligible),
            formatNumber(data.disposed_refresh.due_now),
            data.disposed_refresh.last_run_at
              ? T.data.disposedLastRun(formatDateTime(data.disposed_refresh.last_run_at), formatNumber(data.disposed_refresh.queued_last_run ?? 0))
              : T.data.disposedNoRun,
          )}
        </li>
      </ul>
    </section>
  );
}

const TEXT_KINDS = ["order", "upload", "attachment"] as const;

/** Design document-ocr, decision 4: documents by text status, the ones not read split by type (totals only). */
function DocumentsTextBlock({ data }: { data: DataHealth["documents_text"] }) {
  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.documentsText}>
      <h2>{T.data.documentsText}</h2>
      <p className="muted">{T.data.documentsTextNote}</p>
      <DataTable
        caption={T.data.documentsText}
        rows={[...TEXT_KINDS]}
        rowKey={(kind) => kind}
        columns={[
          { key: "kind", header: T.data.docKind, primary: true, cell: (kind) => T.data.docKinds[kind] },
          { key: "pending", header: T.data.textPending, align: "right", cell: (kind) => formatNumber(data[kind].pending) },
          { key: "extracted", header: T.data.textExtracted, align: "right", cell: (kind) => formatNumber(data[kind].extracted) },
          { key: "failed", header: T.data.textFailed, align: "right", cell: (kind) => formatNumber(data[kind].failed) },
          { key: "scanned", header: T.data.textScannedPdf, align: "right", cell: (kind) => formatNumber(data[kind].none.scanned_pdf) },
          { key: "image", header: T.data.textImage, align: "right", cell: (kind) => formatNumber(data[kind].none.image) },
          { key: "doc", header: T.data.textDoc, align: "right", cell: (kind) => formatNumber(data[kind].none.doc) },
          { key: "other", header: T.data.textOther, align: "right", cell: (kind) => formatNumber(data[kind].none.other) },
        ]}
      />
    </section>
  );
}

/**
 * The connectivity check (either NAPIX function). The re-fetch and reference-list buttons moved to Collect Now (design
 * data-collection-redesign, decisions 28-29); the check moves to Problems and Fixes in round 2.
 */
function Buttons() {
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);

  async function check() {
    setMessage(null);
    const out = await action.run(() => api<HealthCheck>("/admin/napix/health/check", { method: "POST" }));
    if (out.ok) setMessage(out.value.ok ? T.data.checkOk : T.data.checkFailed(out.value.error_family ?? "—"));
  }

  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.actions}>
      <h2>{T.data.actions}</h2>
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      <div className="actions">
        <Button variant="secondary" busy={action.busy} onClick={check}>
          {T.data.check}
        </Button>
      </div>
    </section>
  );
}
