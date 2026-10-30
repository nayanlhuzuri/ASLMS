"use client";

/**
 * My Cases (design case-inbox-simplify, decision 4; API A1): every case I am connected to, read from
 * `GET /inbox/mine?view=all` with its filters in the query string, active and court-disposed together, disposed after
 * active (the API's order), with no status switch; a disposed row reads "Disposed" in the Next Hearing column
 * (`HearingDate`). Rows (Work list template): the case number with the parties under it, the Reason badges from the
 * row's `reasons` (Assigned to Me, Claimed by Me, With Me, in that order), the stage, the next hearing, "Your Action"
 * (the pending action and due date of a case with me) and a chevron; a row opens the case page by click or Enter. The
 * filter bar: the quick chip Hearing This Week, Stage, and the shared filters with Search Words on the first row;
 * "n cases", or "n of m cases" when filtered, m being the `all` figure of `/inbox/mine/counts`.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { FilterBar, type OwnControl } from "@/components/filters/FilterBar";
import { Badge, Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, HearingDate, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, useWorkflowCodes } from "@/lib/api/hooks";
import type { MyCase, MyCaseCounts, MyCaseList } from "@/lib/api/types";
import { FIELD_KEYS, LIST_FILTERS, toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { casePath } from "@/lib/refs";

import { useFilters } from "./common";
import s from "./inbox.module.css";
import { ActionCell, CaseCell, Chevron, CountLine, StageCell } from "./rows";
import { NoCaseMatches } from "@/components/filters/NoCaseMatches";

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

const MINE_KEYS = [...LIST_FILTERS.mine.fields.flatMap((f) => FIELD_KEYS[f]), "stage"];

/** The order of the Reason badges (design case-inbox-simplify, decision 4). */
export const REASON_ORDER = ["allotted", "claimed", "file"] as const;

/** Why the case is in My Cases: one badge per reason, in the fixed order. */
export function ReasonBadges({ reasons }: { reasons: readonly string[] }) {
  const shown = REASON_ORDER.filter((r) => reasons.includes(r));
  if (shown.length === 0) return <span className="muted">—</span>;
  return (
    <span className={s.reasons}>
      {shown.map((r) => (
        <Badge key={r} tone={r === "file" ? "info" : undefined}>
          {T.inbox.reasons[r]}
        </Badge>
      ))}
    </span>
  );
}

export function MyCases({ params, counts }: { params: Params; counts: MyCaseCounts | undefined }) {
  const router = useRouter();
  const setFilters = useFilters(params);
  const stages = useStageOptions();
  const offset = offsetOf(params);
  // no `case_state` and no `action`: there is no status switch, and overdue work is With Me's
  const query = {
    view: "all",
    stage: params.stage || undefined,
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
  const columns: Column<MyCase>[] = [
    { key: "case", header: T.inbox.case, primary: true, cell: (r) => <CaseCell c={r.case} /> },
    { key: "reason", header: T.inbox.reasonCol, cell: (r) => <ReasonBadges reasons={r.reasons} /> },
    { key: "stage", header: T.inbox.stage, cell: (r) => <StageCell stage={r.stage} /> },
    { key: "next", header: T.inbox.nextHearingCol, cell: (r) => <HearingDate next={r.case.next_hearing} status={r.case.status} /> },
    { key: "action", header: T.inbox.yourAction, cell: (r) => <ActionCell custody={r.custody?.with_me ? r.custody : null} /> },
    { key: "open", header: <span className="visually-hidden">{T.inbox.actions}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  return (
    <section className="stack" aria-label={T.tabs.inbox.mine}>
      <ChipGroup label={T.inbox.quick}>
        <Chip on={weekOn} onClick={() => setFilters({ next: weekOn ? undefined : "n7", next_from: undefined, next_to: undefined })}>
          {T.inbox.hearingWeek}
        </Chip>
      </ChipGroup>
      <FilterBar list="mine" params={params} own={own} />
      <div className={s.toolbar}>
        <CountLine total={list.data?.total} of={counts?.all} filtered={isFiltered(params, MINE_KEYS)} />
      </div>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.inbox.mine}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.case.id}
            onRowClick={(r) => router.push(casePath(r.case.ref_no))}
            rowLabel={(r) => T.inbox.openCase(r.case.case_no_text || r.case.ref_no)}
            empty={
              isFiltered(params, MINE_KEYS) ? (
                <NoCaseMatches params={params} list="mine" />
              ) : (
                <EmptyState title={T.inbox.nothingWaiting}>{T.inbox.emptyViews.mine}</EmptyState>
              )
            }
          />
          <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
        </>
      ) : null}
    </section>
  );
}
