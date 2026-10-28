"use client";

/**
 * Case claim → Unclaimed pool (design portal-ui-redesign, decision 6; portal-cases decision 6): cases that have never
 * had a primary owner. Columns: Case, Parties, Next hearing, the best score with the department it was for, and the
 * departments that dismissed it. The pool's portal-filters fields (the shared case filters, "Matched to department",
 * minimum score, "State is a party", "Found by our court search"); an old `status=` link is read as `case_status`. A
 * row opens the details modal, where Claim and Suggest elsewhere are.
 */
import { useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import { CaseCell } from "@/components/inbox/rows";
import { DataTable, EmptyState, ErrorBanner, HearingDate, Loading, Pagination, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY } from "@/lib/api/hooks";
import type { PoolCase, PoolList } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import type { RowContext } from "./CaseModal";
import { partiesText } from "./Recommended";
import { caseFiltersSet, NoCaseMatches } from "@/components/filters/NoCaseMatches";

export function Pool({ params, department, onOpen }: { params: Params; department: string | null; onOpen: (row: RowContext) => void }) {
  const setFilters = useFilters(params);
  const offset = offsetOf(params);
  const query = {
    ...toApiQuery(params, "pool"),
    min_score: params.min_score || undefined,
    state_party: params.state_party || undefined,
    found_for: params.found_for || undefined,
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "pool", query],
    queryFn: () => api<PoolList>("/inbox/pool", { query }),
  });
  const columns: Column<PoolCase>[] = [
    {
      key: "case",
      header: T.inbox.case,
      primary: true,
      cell: (p) => <CaseCell c={{ ...p.case, petitioner_summary: null, respondent_summary: null }} />,
    },
    { key: "parties", header: T.claim.parties, cell: (p) => partiesText(p.case) },
    { key: "next", header: T.claim.nextHearing, cell: (p) => <HearingDate date={p.case.next_hearing_date} status={p.case.status} /> },
    {
      key: "best",
      header: T.claim.best,
      cell: (p) => (p.best_score !== null ? T.inbox.best(p.best_score.toFixed(3), p.best_office_code) : <span className="muted">{T.inbox.noScore}</span>),
    },
    {
      key: "dismissed",
      header: T.claim.dismissedBy,
      cell: (p) => (p.dismissed_by.length > 0 ? p.dismissed_by.join(", ") : <span className="muted">—</span>),
    },
  ];
  return (
    <section className="stack" aria-label={T.tabs.claim.pool}>
      <FilterBar
        list="pool"
        params={params}
        own={[
          { key: "min_score", kind: "number", label: T.inbox.minScore, step: "0.05" },
          {
            key: "state_party",
            kind: "select",
            label: T.inbox.stateParty,
            options: Object.entries(T.inbox.stateParties)
              .filter(([value]) => value)
              .map(([value, label]) => ({ value, label })),
            placeholder: T.inbox.stateParties[""],
            more: true,
          },
          // design department-discovery, decision 13 (c): the department's court-search finds
          ...(department
            ? [
                {
                  key: "found_for",
                  kind: "select" as const,
                  label: T.filters.foundFor,
                  options: [{ value: department, label: department }],
                  placeholder: T.filters.foundForAny,
                },
              ]
            : []),
        ]}
        total={list.data?.total}
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.claim.pool}
            columns={columns}
            rows={list.data.items}
            rowKey={(p) => p.case.id}
            onRowClick={(item) => onOpen({ kind: "pool", item })}
            rowLabel={(p) => T.claim.openRow(p.case.case_no_text || p.case.ref_no)}
            empty={
              caseFiltersSet(params, "pool", ["min_score", "state_party", "found_for"]) ? (
                <NoCaseMatches params={params} list="pool" />
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
