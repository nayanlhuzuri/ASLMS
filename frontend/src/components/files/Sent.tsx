"use client";

/**
 * "Sent by me" (design case-workspace-admin, decisions 17, 19 and 20; custody-workflow decision 24): the legs the caller
 * wrote, sends and recalls, newest first. The case is a link only when the API says the caller can open it (`visible`);
 * otherwise its number is text, never a link to a 404. A leg that is no longer the case's current leg is muted
 * (`current` false); for a case the caller can no longer open `current` is null and the row says nothing about where
 * the case went. The remark is the caller's own. The one filter bar (design portal-filters): the shared case filters
 * with the owning department. Work list template: case and parties ("Recalled" marked under the number for a recall),
 * action needed with its Due line, Sent to and the chevron (design portal-screen-fixes-work, decisions 2 to 5: no lead
 * column, the inbox's one plain case cell, overdue and due soon counted in the browser as legs carry no flag; Layout B
 * with "Search" and "n cases" or "n cases match" at the head of the strip, decision 1).
 *
 * Design case-inbox-simplify, decisions 6 and 7: by default the files still out (`still_out=true`: sends still the
 * case's current leg, on a case the caller can open, not held by the caller, overdue first); "Show Earlier"
 * (`earlier=true`) drops the filter and shows every send and recall, newest first, with legs that have moved on muted.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { ActionDueCell, CaseCell, Chevron, CountLine, DueLine } from "@/components/inbox/rows";
import { DataTable, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { SentItem, SentList } from "@/lib/api/types";
import { legHolder, sentDue } from "@/lib/cases";
import { toApiQuery } from "@/lib/filters";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { serverLabel } from "@/lib/displayLabels";

import { FilePanel } from "./FilePanel";
import { CUSTODY_MORE, WithCell } from "./Held";
import s from "./files.module.css";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

export function Sent({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const [open, setOpen] = useState<SentItem | null>(null);
  const offset = offsetOf(params);
  const earlier = params.earlier === "true";
  const query = { still_out: earlier ? undefined : true, ...toApiQuery(params, "sent"), limit: PAGE, offset };
  const own: OwnControl[] = [{ key: "earlier", kind: "check", label: T.files.showEarlier, first: true }];
  const list = useQuery({
    queryKey: ["files", "sent", query],
    queryFn: () => api<SentList>("/custody/sent", { query }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<SentItem>[] = [
    {
      key: "case",
      header: T.files.case,
      primary: true,
      cell: (r) => <CaseCell c={r.case} marks={[r.leg.reason === "recalled" ? { label: T.cases.recalledMark } : null]} />,
    },
    {
      key: "action",
      header: T.files.action,
      cell: (r) => (
        <ActionDueCell
          action={r.leg.pending_action && r.leg.pending_action !== "none" ? (serverLabel(r.leg.pending_action_label) ?? r.leg.pending_action) : null}
          due={sentDue(r)}
        />
      ),
    },
    { key: "to", header: T.cases.sentTo, cell: (r) => <WithCell party={legHolder(r.leg)} /> },
    { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  // "Show Earlier" is the list's view, not a filter (design case-inbox-simplify, decision 6)
  const filtered = caseFiltersSet(params, "sent");
  const leg = open?.leg;
  return (
    <div className="stack">
      <FilterBar
        list="sent"
        layout="card"
        hero="q"
        more={CUSTODY_MORE}
        params={params}
        own={own}
        wordsLabel={T.filters.wordsShort}
        wordsHint={T.filters.wordsHint}
        countLine={list.data ? <CountLine total={list.data.total} of={null} filtered={filtered} /> : null}
      />
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
            rowClassName={(r) => (earlier && r.current === false ? s.mutedRow : undefined)}
            empty={
              filtered ? (
                <NoCaseMatches params={params} list="sent" />
              ) : (
                <EmptyState title={T.files.emptySentTitle}>{earlier ? T.files.emptySent : T.files.emptyStillOut}</EmptyState>
              )
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
          [T.files.action, serverLabel(leg?.pending_action_label) ?? null],
          [T.files.since, formatDateTime(leg?.started_at)],
          [T.files.due, open ? <DueLine due={sentDue(open)} /> : null],
          [T.files.reason, serverLabel(leg?.reason_label) ?? null],
        ]}
      />
    </div>
  );
}
