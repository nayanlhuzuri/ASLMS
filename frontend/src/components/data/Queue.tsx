"use client";

/**
 * Queue rows and the call log (design audit-screens, decision 7; data-load-console, decision 19): queue rows by kind,
 * status, lane and reference prefix with Retry (by the row's function), and the call log of today (IST) with a keyset
 * "More", each call's lane and, when the API returns it (the NAPIX operators only), the user who caused it (design
 * napix-window). Never the call parameters.
 */
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, DataTable, EmptyState, ErrorBanner, Loading, Pagination, SelectField, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { CallList, QueueList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

const LIMIT = 50;
const STATUSES = ["pending", "running", "done", "failed", "skipped"];

export function QueueAndCalls() {
  return (
    <section className="stack" aria-label={T.data.queueRows}>
      <QueueRows />
      <CallLog />
    </section>
  );
}

function QueueRows() {
  const me = useMe();
  const queryClient = useQueryClient();
  const action = useAction();
  const [filter, setFilter] = useState({ kind: "", status: "", lane: "", ref: "" });
  const [offset, setOffset] = useState(0);
  const rows = useQuery({
    queryKey: ["data-queue", filter, offset],
    queryFn: () =>
      api<QueueList>("/admin/napix/queue", {
        query: { kind: filter.kind, status: filter.status, lane: filter.lane, ref: filter.ref, limit: LIMIT, offset },
      }),
  });
  const mayRetry = (kind: string) => can(me.data, kind === "masters" ? "admin.masters_sync" : "admin.napix_refetch");
  async function retry(id: string) {
    const out = await action.run(() => api(`/admin/napix/queue/${id}/retry`, { method: "POST" }));
    if (out.ok) await queryClient.invalidateQueries({ queryKey: ["data-queue"] });
  }
  const set = (patch: Partial<typeof filter>) => {
    setFilter({ ...filter, ...patch });
    setOffset(0);
  };
  return (
    <section className={`stack ${ds.panel}`} aria-label={T.data.queueRows}>
      <h2>{T.data.queueRows}</h2>
      <div className="row">
        <SelectField
          label={T.data.kind}
          value={filter.kind}
          placeholder={T.data.allKinds}
          onChange={(e) => set({ kind: e.target.value })}
          options={Object.entries(T.data.kinds).map(([value, label]) => ({ value, label }))}
        />
        <SelectField
          label={T.data.status}
          value={filter.status}
          placeholder={T.data.allStatuses}
          onChange={(e) => set({ status: e.target.value })}
          options={STATUSES.map((value) => ({ value, label: value }))}
        />
        <SelectField
          label={T.data.lane}
          value={filter.lane}
          placeholder={T.data.allLanes}
          onChange={(e) => set({ lane: e.target.value })}
          options={["request", "daily", "discovery", "load"].map((value) => ({ value, label: T.data.lanes[value] ?? value }))}
        />
        <TextField label={T.data.refPrefix} value={filter.ref} onChange={(e) => set({ ref: e.target.value })} />
      </div>
      <ErrorBanner error={rows.error ?? action.error} onRetry={() => rows.refetch()} />
      {rows.isPending ? <Loading /> : null}
      {rows.data ? (
        rows.data.items.length === 0 ? (
          <EmptyState>{T.data.noDuplicates}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.data.queueRows}
              rows={rows.data.items}
              rowKey={(r) => r.id}
              columns={[
                { key: "kind", header: T.data.kind, cell: (r) => T.data.kinds[r.kind] ?? r.kind },
                { key: "ref", header: T.data.ref, primary: true, cell: (r) => <span className="mono">{r.ref}</span> },
                { key: "lane", header: T.data.lane, cell: (r) => T.data.lanes[r.lane] ?? r.lane },
                { key: "priority", header: T.data.priority, align: "right", cell: (r) => r.priority },
                { key: "status", header: T.data.status, width: "var(--lead-w)", cell: (r) => r.status },
                { key: "attempts", header: T.data.attempts, align: "right", cell: (r) => r.attempts },
                { key: "error", header: T.data.lastError, cell: (r) => r.last_error ?? "—" },
                {
                  key: "retry",
                  header: <span className="visually-hidden">{T.data.retry}</span>,
                  label: T.data.retry,
                  cell: (r) =>
                    (r.status === "failed" || r.status === "skipped") && mayRetry(r.kind) ? (
                      <Button variant="link" busy={action.busy} onClick={() => retry(r.id)}>
                        {T.data.retry}
                      </Button>
                    ) : null,
                },
              ]}
            />
            <Pagination offset={offset} limit={LIMIT} total={rows.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}

function CallLog() {
  const calls = useInfiniteQuery({
    queryKey: ["data-calls"],
    queryFn: ({ pageParam }) => api<CallList>("/admin/napix/calls", { query: { cursor: pageParam, limit: LIMIT } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = calls.data?.pages.flatMap((p) => p.items) ?? [];
  const showUsers = items.some((c) => c.user_id);
  return (
    <section className={`stack ${ds.panel}`} aria-label={T.data.callLog}>
      <h2>{T.data.callLog}</h2>
      <ErrorBanner error={calls.error} onRetry={() => calls.refetch()} />
      {calls.isPending ? <Loading /> : null}
      {calls.data ? (
        items.length === 0 ? (
          <EmptyState>{T.data.noDuplicates}</EmptyState>
        ) : (
          <DataTable
            caption={T.data.callLog}
            rows={items}
            rowKey={(c) => c.id}
            columns={[
              { key: "at", header: T.data.at, primary: true, cell: (c) => formatDateTime(c.called_at) },
              { key: "api", header: T.data.api, cell: (c) => <span className="mono">{c.api}</span> },
              { key: "lane", header: T.data.lane, cell: (c) => (c.lane ? (T.data.lanes[c.lane] ?? c.lane) : T.data.lanes.outside_queue) },
              ...(showUsers
                ? [{ key: "user", header: T.data.user, cell: (c: (typeof items)[number]) => c.user_name ?? "—" }]
                : []),
              { key: "ok", header: T.data.ok, cell: (c) => (c.ok ? T.yes : T.no) },
              { key: "http", header: T.data.http, align: "right", cell: (c) => c.http_status ?? "—" },
              { key: "remaining", header: T.data.remaining("").trim(), align: "right", cell: (c) => c.rate_limit_remaining ?? "—" },
              { key: "error", header: T.data.lastError, cell: (c) => c.error_family ?? "—" },
            ]}
          />
        )
      ) : null}
      {calls.hasNextPage ? (
        <div>
          <Button variant="secondary" busy={calls.isFetchingNextPage} onClick={() => calls.fetchNextPage()}>
            {T.data.more}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
