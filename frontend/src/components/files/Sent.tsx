"use client";

/**
 * "Sent by me" (design case-workspace-admin, decisions 17, 19 and 20; custody-workflow decision 24): the legs the caller
 * wrote, sends and recalls, newest first. The case is a link only when the API says the caller can open it (`visible`);
 * otherwise its number is text, never a link to a 404. A leg that is no longer the case's current leg is muted
 * (`current` false); for a case the caller can no longer open `current` is null and the row says nothing about where
 * the case went. The remark is the caller's own. The one filter bar (design portal-filters): the shared case filters
 * with the owning department. Work list template: the lead badge (Overdue, Due soon or Waiting while the leg is
 * current), case and parties ("Recalled" under the number for a recall), action needed, due by, Sent to and the chevron.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { Chevron } from "@/components/inbox/rows";
import { DataTable, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { SentItem, SentList } from "@/lib/api/types";
import { leadBadge, legHolder } from "@/lib/cases";
import { toApiQuery } from "@/lib/filters";
import { formatDate, formatDateTime, istDay } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import { FilePanel } from "./FilePanel";
import { CaseCell, DueCell, LeadCell, WithCell } from "./Held";
import s from "./files.module.css";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

function overdue(item: SentItem): boolean {
  return item.current === true && !!item.leg.due_date && item.leg.due_date < istDay();
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
    {
      key: "lead",
      header: <span className="visually-hidden">{T.cases.leadCol}</span>,
      label: T.cases.leadCol,
      width: "var(--lead-w)",
      cell: (r) => <LeadCell badge={leadBadge(r, "sent")} />,
    },
    {
      key: "case",
      header: T.files.case,
      primary: true,
      cell: (r) => <CaseCell c={r.case} visible={r.visible} mark={r.leg.reason === "recalled" ? T.cases.recalledMark : null} />,
    },
    { key: "action", header: T.files.action, cell: (r) => r.leg.pending_action_label },
    { key: "due", header: T.files.due, cell: (r) => <DueCell date={r.leg.due_date} overdue={overdue(r)} /> },
    { key: "to", header: T.cases.sentTo, cell: (r) => <WithCell party={legHolder(r.leg)} /> },
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
            rowClassName={(r) => (r.current === false ? s.mutedRow : undefined)}
            empty={
              caseFiltersSet(params, "sent") ? <NoCaseMatches params={params} list="sent" /> : <EmptyState>{T.files.emptySent}</EmptyState>
            }
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
          [T.cases.sentTo, open ? <WithCell party={legHolder(open.leg)} /> : null],
          [T.files.action, leg?.pending_action_label ?? null],
          [T.files.since, formatDateTime(leg?.started_at)],
          [T.files.due, leg?.due_date ? formatDate(leg.due_date) : null],
          [T.files.reason, leg?.reason_label ?? null],
        ]}
      />
    </div>
  );
}
