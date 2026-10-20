"use client";

/**
 * The Case inbox's own-work views (design portal-ui-redesign, decision 5; API A1): Working on, Files with me, Claimed
 * by me and Disposed, each read from `GET /inbox/mine?view=…` with its filters in the query string. Rows (Work list
 * template): the case number with the parties under it, the stage, the next hearing with its badge, "Your action" (the
 * pending action and due date of a file with me) and a chevron; a row opens the case page by click or Enter. The filter
 * bar: quick chips (Hearing this week, Action overdue), Stage, and "More filters" (words, case type, year, court);
 * "n cases", or "n of m cases" when filtered, m being the tab's unfiltered count from `/inbox/mine/counts`.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useWorkflowCodes } from "@/lib/api/hooks";
import type { MyCase, MyCaseCounts, MyCaseList } from "@/lib/api/types";
import { FIELD_KEYS, LIST_FILTERS, toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { casePath } from "@/lib/refs";
import type { MyView } from "@/lib/routes";

import { useFilters } from "./common";
import s from "./inbox.module.css";
import { ActionCell, CaseCell, Chevron, CountLine, NextHearingCell, StageCell } from "./rows";

/** The stage choices: any, "No stage set" (`none`) and the catalogue's stages. */
export function useStageOptions() {
  const codes = useWorkflowCodes();
  return [
    { value: "none", label: T.inbox.noStage },
    ...(codes.data?.stages ?? []).map((st) => ({ value: st.code, label: st.label })),
  ];
}

/** Whether any filter of the list (shared or own) is set: the count line then reads "n of m". */
export function isFiltered(params: Params, keys: string[]): boolean {
  return keys.some((k) => !!params[k]);
}

const MINE_KEYS = [...LIST_FILTERS.mine.fields.flatMap((f) => FIELD_KEYS[f]), "stage", "action"];

export function MyCases({ view, params, counts }: { view: MyView; params: Params; counts: MyCaseCounts | undefined }) {
  const router = useRouter();
  const setFilters = useFilters(params);
  const stages = useStageOptions();
  const offset = offsetOf(params);
  const query = {
    view,
    stage: params.stage || undefined,
    action: params.action || undefined,
    ...toApiQuery(params, "mine"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "mine", query],
    queryFn: () => api<MyCaseList>("/inbox/mine", { query }),
  });
  const own: OwnControl[] = [{ key: "stage", kind: "select", label: T.inbox.stage, options: stages, placeholder: T.inbox.anyStage }];
  const weekOn = params.next === "n7" && !params.next_from && !params.next_to;
  const overdueOn = params.action === "overdue";
  const columns: Column<MyCase>[] = [
    { key: "case", header: T.inbox.case, primary: true, cell: (r) => <CaseCell c={r.case} /> },
    { key: "stage", header: T.inbox.stage, cell: (r) => <StageCell stage={r.stage} /> },
    { key: "next", header: T.inbox.nextHearingCol, cell: (r) => <NextHearingCell date={r.case.next_hearing_date} /> },
    { key: "action", header: T.inbox.yourAction, cell: (r) => <ActionCell custody={r.custody?.with_me ? r.custody : null} /> },
    { key: "open", header: <span className="visually-hidden">{T.inbox.actions}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  return (
    <section className="stack" aria-label={T.tabs.inbox[view]}>
      <ChipGroup label={T.inbox.quick}>
        <Chip on={weekOn} onClick={() => setFilters({ next: weekOn ? undefined : "n7", next_from: undefined, next_to: undefined })}>
          {T.inbox.hearingWeek}
        </Chip>
        <Chip on={overdueOn} onClick={() => setFilters({ action: overdueOn ? undefined : "overdue" })}>
          {T.inbox.actionOverdue}
        </Chip>
      </ChipGroup>
      <FilterBar list="mine" params={params} own={own} />
      <div className={s.toolbar}>
        <CountLine total={list.data?.total} of={counts?.[view]} filtered={isFiltered(params, MINE_KEYS)} />
      </div>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.inbox[view]}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.case.id}
            onRowClick={(r) => router.push(casePath(r.case.ref_no))}
            rowLabel={(r) => T.inbox.openCase(r.case.case_no_text || r.case.ref_no)}
            empty={<EmptyState title={T.inbox.nothingWaiting}>{T.inbox.emptyViews[view]}</EmptyState>}
          />
          <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
        </>
      ) : null}
    </section>
  );
}
