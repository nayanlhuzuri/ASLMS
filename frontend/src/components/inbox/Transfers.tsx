"use client";

/**
 * The Transfers tab (design portal-cases, decision 6): In / Out and status. In rows still requested offer Accept /
 * Decline with `cases.transfer_decide`; Out rows still requested offer Withdraw with `cases.transfer_request` (both in
 * the selected department's membership). The one filter bar (design portal-filters): the shared case filters, "Other
 * department" (`other_office`) and the transfer's status.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import { Badge, Button, CaseLink, EmptyState, ErrorBanner, Loading, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useMe } from "@/lib/api/hooks";
import type { TransferList } from "@/lib/api/types";
import { canIn } from "@/lib/can";
import { toApiQuery } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { PartiesLine, useFilters } from "./common";
import { OwnershipDialogs, type DialogKind } from "./dialogs";

const DIRECTIONS = ["in", "out"] as const;

function statusTone(status: string) {
  return status === "accepted" ? "success" : status === "declined" ? "danger" : status === "requested" ? "warning" : undefined;
}

export function Transfers({ params, department }: { params: Params; department: string }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const direction = params.direction === "out" ? "out" : "in";
  const offset = offsetOf(params);
  const query = {
    office: department,
    direction,
    status: params.status || undefined,
    ...toApiQuery(params, "transfers"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "transfers", query],
    queryFn: () => api<TransferList>("/inbox/transfers", { query }),
  });
  const canDecide = canIn(me.data, department, "cases.transfer_decide");
  const canWithdraw = canIn(me.data, department, "cases.transfer_request");
  return (
    <section className="stack" aria-label={T.inbox.direction}>
      <div className="row">
        <div className="row" role="group" aria-label={T.inbox.direction}>
          {DIRECTIONS.map((d) => (
            <Button
              key={d}
              variant={d === direction ? "primary" : "secondary"}
              aria-pressed={d === direction}
              onClick={() => setFilters({ direction: d === "in" ? undefined : d })}
            >
              {T.inbox.directions[d]}
            </Button>
          ))}
        </div>
      </div>
      <FilterBar
        list="transfers"
        params={params}
        own={[
          {
            key: "status",
            kind: "select",
            label: T.inbox.transferStatus,
            options: Object.entries(T.inbox.transferStatuses)
              .filter(([value]) => value)
              .map(([value, label]) => ({ value, label })),
            placeholder: T.inbox.transferStatuses[""],
          },
        ]}
        total={list.data?.total}
        noun="transfers"
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.inbox.empty}</EmptyState>
        ) : (
          <>
            <Table caption={T.inbox.directions[direction]}>
              <thead>
                <tr>
                  <th scope="col">{T.inbox.case}</th>
                  <th scope="col">{T.inbox.direction}</th>
                  <th scope="col">{T.inbox.status}</th>
                  <th scope="col">{T.inbox.actions}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((t) => {
                  const open = t.status === "requested";
                  return (
                    <tr key={t.id}>
                      <td>
                        <div className="mono muted">{t.ref_no}</div>
                        <PartiesLine c={t.case} />
                        <CaseLink value={t.case} />
                      </td>
                      <td>
                        <div className="mono">{T.inbox.fromTo(t.from_office_code, t.to_office_code)}</div>
                        {t.reason ? <div>{t.reason}</div> : null}
                        <div className="muted">
                          {T.inbox.requested(t.requested_by?.full_name ?? "—", formatDate(t.requested_at))}
                          {t.stay_as_watcher ? ` · ${T.inbox.stayWatcher}` : ""}
                        </div>
                      </td>
                      <td>
                        <Badge tone={statusTone(t.status)}>{T.inbox.transferStatuses[t.status] ?? t.status}</Badge>
                        {t.decision_note ? <div className="muted">{t.decision_note}</div> : null}
                      </td>
                      <td>
                        <div className="row">
                          {open && direction === "in" && canDecide ? (
                            <>
                              <Button
                                onClick={() =>
                                  setDialog({ kind: "decide", caseRef: t.case.ref_no, transferId: t.id, accept: true })
                                }
                              >
                                {T.own.accept}
                              </Button>
                              <Button
                                variant="secondary"
                                onClick={() =>
                                  setDialog({ kind: "decide", caseRef: t.case.ref_no, transferId: t.id, accept: false })
                                }
                              >
                                {T.own.decline}
                              </Button>
                            </>
                          ) : null}
                          {open && direction === "out" && canWithdraw ? (
                            <Button
                              variant="secondary"
                              onClick={() => setDialog({ kind: "withdraw", caseRef: t.case.ref_no, transferId: t.id })}
                            >
                              {T.own.withdraw}
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              offset={offset}
              limit={PAGE}
              total={list.data.total}
              onChange={(o) => setFilters({ offset: String(o) })}
            />
          </>
        )
      ) : null}
      <OwnershipDialogs open={dialog} onClose={() => setDialog(null)} department={department} />
    </section>
  );
}
