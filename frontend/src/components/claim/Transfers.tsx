"use client";

/**
 * Case claim → Transfers to us (design portal-ui-redesign, decision 6; portal-cases decision 6): by default the
 * transfers to the department still requested. The two-way switch "To us | From us" keeps the outgoing transfers
 * (and Withdraw, in the modal) reachable, and the status filter stays ("Any" shows every status). Columns: Case, the
 * other department, the reason, who requested it and when, and the status. A row opens the details modal, whose
 * footer holds Accept / Decline (or Withdraw for an outgoing transfer) by the server's `actions`.
 */
import { useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { CaseCell } from "@/components/inbox/rows";
import { Badge, DataTable, EmptyState, ErrorBanner, Loading, Pagination, SegmentedSwitch, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY } from "@/lib/api/hooks";
import type { Transfer, TransferList } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import type { RowContext } from "./CaseModal";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

/** `status=all` in the URL is "Any"; without a status, In shows the requested ones. */
export const ANY_STATUS = "all";

function statusTone(status: string) {
  return status === "accepted" ? "success" : status === "declined" ? "danger" : status === "requested" ? "info" : undefined;
}

export function transferStatusOf(params: Params): string {
  const direction = params.direction === "out" ? "out" : "in";
  return params.status || (direction === "in" ? "requested" : ANY_STATUS);
}

export function Transfers({ params, department, onOpen }: { params: Params; department: string; onOpen: (row: RowContext) => void }) {
  const setFilters = useFilters(params);
  const direction = params.direction === "out" ? "out" : "in";
  const status = transferStatusOf(params);
  const offset = offsetOf(params);
  const query = {
    office: department,
    direction,
    status: status === ANY_STATUS ? undefined : status,
    ...toApiQuery(params, "transfers"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "transfers", query],
    queryFn: () => api<TransferList>("/inbox/transfers", { query }),
  });
  const columns: Column<Transfer>[] = [
    { key: "case", header: T.inbox.case, primary: true, cell: (t) => <CaseCell c={t.case} /> },
    {
      key: "other",
      header: T.inbox.direction,
      cell: (t) => <span className="mono">{T.inbox.fromTo(t.from_office_code, t.to_office_code)}</span>,
    },
    { key: "reason", header: T.claim.reason, cell: (t) => t.reason ?? <span className="muted">—</span> },
    {
      key: "requested",
      header: T.claim.requested,
      cell: (t) => (
        <span className="muted">
          {T.inbox.requested(t.requested_by?.full_name ?? "—", formatDate(t.requested_at))}
          {t.stay_as_watcher ? ` · ${T.inbox.stayWatcher}` : ""}
        </span>
      ),
    },
    {
      key: "status",
      header: T.claim.status,
      width: "var(--lead-w)",
      cell: (t) => <Badge tone={statusTone(t.status)}>{T.inbox.transferStatuses[t.status] ?? t.status}</Badge>,
    },
  ];
  return (
    <section className="stack" aria-label={T.tabs.claim.transfers}>
      <SegmentedSwitch
        label={T.claim.direction}
        options={(["in", "out"] as const).map((d) => ({ value: d, label: T.claim.directions[d]! }))}
        value={direction}
        onChange={(d) => setFilters({ direction: d === "in" ? undefined : d, status: undefined })}
      />
      <FilterBar
        list="transfers"
        params={{ ...params, status }}
        own={[
          {
            key: "status",
            kind: "select",
            label: T.inbox.transferStatus,
            options: [
              { value: ANY_STATUS, label: T.inbox.transferStatuses[""]! },
              ...Object.entries(T.inbox.transferStatuses)
                .filter(([value]) => value)
                .map(([value, label]) => ({ value, label })),
            ],
          },
        ]}
        total={list.data?.total}
        noun="transfers"
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.claim.directions[direction]}
            showCaption
            columns={columns}
            rows={list.data.items}
            rowKey={(t) => t.id}
            onRowClick={(transfer) => onOpen({ kind: "transfer", transfer })}
            rowLabel={(t) => T.claim.openRow(t.case.case_no_text || t.case.ref_no)}
            empty={
              caseFiltersSet(params, "transfers", ["status"]) ? (
                <NoCaseMatches params={params} list="transfers" />
              ) : (
                <EmptyState title={T.inbox.nothingWaiting}>{T.inbox.empty}</EmptyState>
              )
            }
          />
          <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
        </>
      ) : null}
    </section>
  );
}
