"use client";

/**
 * "Sent" (design portal-files-alerts, decision 12; custody-workflow decision 24): the legs the caller wrote, sends and
 * recalls, newest first. The case is a link only when the API says the caller can open it (`visible`); otherwise its
 * number is text, never a link to a 404. The remark is the caller's own. The one filter bar (design portal-filters):
 * the shared case filters with the owning department; they match the facts the row already shows.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { CaseLink, EmptyState, ErrorBanner, Loading, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { SentItem, SentList } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { Remark } from "./Remark";

function SentTo({ item }: { item: SentItem }) {
  const leg = item.leg;
  return (
    <>
      {leg.holder_user ? <div>{[leg.holder_user.full_name, leg.holder_designation].filter(Boolean).join(", ")}</div> : null}
      <div>
        <span className="mono">{leg.holder_office.code}</span> {leg.holder_office.name}
      </div>
    </>
  );
}

export function Sent({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const offset = offsetOf(params);
  const query = { ...toApiQuery(params, "sent"), limit: PAGE, offset };
  const list = useQuery({
    queryKey: ["files", "sent", query],
    queryFn: () => api<SentList>("/custody/sent", { query }),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="stack">
      <FilterBar list="sent" params={params} total={list.data?.total} noun="files" />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.files.emptySent}</EmptyState>
        ) : (
          <>
            <Table caption={T.files.captionSent}>
              <thead>
                <tr>
                  <th scope="col">{T.files.when}</th>
                  <th scope="col">{T.files.case}</th>
                  <th scope="col">{T.files.reason}</th>
                  <th scope="col">{T.files.sentTo}</th>
                  <th scope="col">{T.files.action}</th>
                  <th scope="col">{T.files.due}</th>
                  <th scope="col">{T.files.remark}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={`${item.case.id}-${item.leg.seq_no}`}>
                    <td>{formatDateTime(item.leg.started_at)}</td>
                    <td>
                      <CaseLink value={item.case} visible={item.visible} />
                    </td>
                    <td>{item.leg.reason_label}</td>
                    <td>
                      <SentTo item={item} />
                    </td>
                    <td>{item.leg.pending_action_label}</td>
                    <td>{item.leg.due_date ? formatDate(item.leg.due_date) : "—"}</td>
                    <td>
                      <Remark text={item.leg.remark} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
    </div>
  );
}
