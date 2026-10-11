"use client";

/**
 * Queue rows and the call log (design audit-screens, decision 7; data-load-console, decision 19): queue rows by kind,
 * status, lane and reference prefix with Retry (by the row's function), and the call log of today (IST) with a keyset
 * "More". Never the call parameters.
 */
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, EmptyState, ErrorBanner, Loading, numCell, Pagination, SelectField, Table, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { CallList, QueueList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

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
    <section className="stack" aria-label={T.data.queueRows}>
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
          options={["request", "daily", "load"].map((value) => ({ value, label: T.data.lanes[value] ?? value }))}
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
            <Table caption={T.data.queueRows}>
              <thead>
                <tr>
                  <th scope="col">{T.data.kind}</th>
                  <th scope="col">{T.data.ref}</th>
                  <th scope="col">{T.data.lane}</th>
                  <th scope="col" className={numCell}>{T.data.priority}</th>
                  <th scope="col">{T.data.status}</th>
                  <th scope="col" className={numCell}>{T.data.attempts}</th>
                  <th scope="col">{T.data.lastError}</th>
                  <th scope="col">
                    <span className="visually-hidden">{T.data.retry}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>{T.data.kinds[r.kind] ?? r.kind}</td>
                    <td className="mono">{r.ref}</td>
                    <td>{T.data.lanes[r.lane] ?? r.lane}</td>
                    <td className={numCell}>{r.priority}</td>
                    <td>{r.status}</td>
                    <td className={numCell}>{r.attempts}</td>
                    <td>{r.last_error ?? "—"}</td>
                    <td>
                      {(r.status === "failed" || r.status === "skipped") && mayRetry(r.kind) ? (
                        <Button variant="link" busy={action.busy} onClick={() => retry(r.id)}>
                          {T.data.retry}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
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
  return (
    <section className="stack" aria-label={T.data.callLog}>
      <h2>{T.data.callLog}</h2>
      <ErrorBanner error={calls.error} onRetry={() => calls.refetch()} />
      {calls.isPending ? <Loading /> : null}
      {calls.data ? (
        items.length === 0 ? (
          <EmptyState>{T.data.noDuplicates}</EmptyState>
        ) : (
          <Table caption={T.data.callLog}>
            <thead>
              <tr>
                <th scope="col">{T.data.at}</th>
                <th scope="col">{T.data.api}</th>
                <th scope="col">{T.data.ok}</th>
                <th scope="col" className={numCell}>HTTP</th>
                <th scope="col" className={numCell}>{T.data.remaining("").trim()}</th>
                <th scope="col">{T.data.lastError}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>{formatDateTime(c.called_at)}</td>
                  <td className="mono">{c.api}</td>
                  <td>{c.ok ? T.yes : T.no}</td>
                  <td className={numCell}>{c.http_status ?? "—"}</td>
                  <td className={numCell}>{c.rate_limit_remaining ?? "—"}</td>
                  <td>{c.error_family ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
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
