"use client";

/**
 * "Sent" (design portal-files-alerts, decision 12; custody-workflow decision 24): the legs the caller wrote, sends and
 * recalls, newest first. The case is a link only when the API says the caller can open it (`visible`); otherwise its
 * number is text, never a link to a 404. The remark is the caller's own. The one filter bar (design portal-filters):
 * the shared case filters with the owning department; they match the facts the row already shows. On the Work list
 * template (design portal-ui-redesign, decision 26): the day it was sent in the fixed leading column, cards on phones,
 * and the leg's details with the full remark in a side panel opened by the row.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { Chevron } from "@/components/inbox/rows";
import { CaseLink, DataTable, DateChip, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { SentItem, SentList } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { FilePanel } from "./FilePanel";

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
  const [open, setOpen] = useState<SentItem | null>(null);
  const offset = offsetOf(params);
  const query = { ...toApiQuery(params, "sent"), limit: PAGE, offset };
  const list = useQuery({
    queryKey: ["files", "sent", query],
    queryFn: () => api<SentList>("/custody/sent", { query }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<SentItem>[] = [
    { key: "when", header: T.files.when, width: "calc(var(--date-w) + var(--s6))", cell: (r) => <DateChip date={r.leg.started_at} /> },
    { key: "case", header: T.files.case, primary: true, cell: (r) => <CaseLink value={r.case} visible={r.visible} /> },
    { key: "reason", header: T.files.reason, cell: (r) => r.leg.reason_label },
    { key: "to", header: T.files.sentTo, cell: (r) => <SentTo item={r} /> },
    { key: "action", header: T.files.action, cell: (r) => r.leg.pending_action_label },
    { key: "due", header: T.files.due, hideOnPhone: true, cell: (r) => (r.leg.due_date ? formatDate(r.leg.due_date) : "—") },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  const leg = open?.leg;
  return (
    <div className="stack">
      <FilterBar list="sent" params={params} total={list.data?.total} noun="files" />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.files.captionSent}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => `${r.case.id}-${r.leg.seq_no}`}
            onRowClick={setOpen}
            rowLabel={(r) => T.files.openFile(r.case.case_no_text || r.case.ref_no)}
            empty={<EmptyState>{T.files.emptySent}</EmptyState>}
          />
          {list.data.items.length > 0 ? (
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          ) : null}
        </>
      ) : null}
      <FilePanel
        caseRef={open ? open.case : null}
        visible={open?.visible ?? false}
        onClose={() => setOpen(null)}
        remark={leg?.remark}
        facts={[
          [T.files.when, formatDateTime(leg?.started_at)],
          [T.files.reason, leg?.reason_label ?? null],
          [T.files.sentTo, open ? <SentTo item={open} /> : null],
          [T.files.action, leg?.pending_action_label ?? null],
          [T.files.due, leg?.due_date ? formatDate(leg.due_date) : null],
        ]}
      />
    </div>
  );
}
