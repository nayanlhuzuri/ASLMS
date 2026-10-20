"use client";

/**
 * Case claim → Recommended (design portal-ui-redesign, decision 6; portal-cases decision 5): the department's active
 * recommendations in the API's order (strong first, score, next hearing). Columns: Case, Parties, Next hearing (with
 * the 48 h badge), Match — "Strong · 0.950" for `high`, "Possible · 0.620" for `medium`, from the API's `band`, the
 * score as stored to three decimals. Quick chips Strong, Possible and Listed this week, then the portal-filters fields
 * of this list. Rows carry no buttons or signal chips: a click (or Enter on the focused row) opens the details modal,
 * where the signals and the actions are.
 */
import { useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { CaseCell, NextHearingCell } from "@/components/inbox/rows";
import { useFilters } from "@/components/inbox/common";
import { Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, Loading, Pagination, ScoreBadge, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY } from "@/lib/api/hooks";
import type { Recommendation, RecommendationList } from "@/lib/api/types";
import { toApiQuery } from "@/lib/filters";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

import type { RowContext } from "./CaseModal";

export function partiesText(c: { petitioner_summary: string | null; respondent_summary: string | null }) {
  if (!c.petitioner_summary && !c.respondent_summary) return <span className="muted">—</span>;
  return (
    <span>
      {c.petitioner_summary ?? "—"} <span className="muted">{T.vs}</span> {c.respondent_summary ?? "—"}
    </span>
  );
}

export function Recommended({ params, department, onOpen }: { params: Params; department: string; onOpen: (row: RowContext) => void }) {
  const setFilters = useFilters(params);
  const offset = offsetOf(params);
  const query = {
    office: department,
    band: params.band || undefined,
    ...toApiQuery(params, "recommended"),
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: [...INBOX_KEY, "recommended", query],
    queryFn: () => api<RecommendationList>("/inbox/recommended", { query }),
  });
  const band = params.band;
  const weekOn = params.listed === "d7" && !params.listed_from && !params.listed_to;
  const columns: Column<Recommendation>[] = [
    {
      key: "case",
      header: T.inbox.case,
      primary: true,
      cell: (r) => <CaseCell c={{ ...r.case, petitioner_summary: null, respondent_summary: null }} />,
    },
    { key: "parties", header: T.claim.parties, cell: (r) => partiesText(r.case) },
    { key: "next", header: T.claim.nextHearing, cell: (r) => <NextHearingCell date={r.case.next_hearing_date} /> },
    { key: "match", header: T.claim.match, width: "180px", cell: (r) => <ScoreBadge score={r.score} band={r.band} /> },
  ];
  return (
    <section className="stack" aria-label={T.tabs.claim.recommended}>
      <ChipGroup label={T.claim.quick}>
        <Chip on={band === "high"} onClick={() => setFilters({ band: band === "high" ? undefined : "high" })}>
          {T.claim.strong}
        </Chip>
        <Chip on={band === "medium"} onClick={() => setFilters({ band: band === "medium" ? undefined : "medium" })}>
          {T.claim.possible}
        </Chip>
        <Chip on={weekOn} onClick={() => setFilters({ listed: weekOn ? undefined : "d7", listed_from: undefined, listed_to: undefined })}>
          {T.claim.listedWeek}
        </Chip>
      </ChipGroup>
      <FilterBar
        list="recommended"
        params={params}
        own={[
          {
            key: "band",
            kind: "select",
            label: T.inbox.strength,
            options: Object.entries(T.inbox.strengths)
              .filter(([value]) => value)
              .map(([value, label]) => ({ value, label })),
            placeholder: T.inbox.strengths[""],
          },
        ]}
        total={list.data?.total}
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        <>
          <DataTable
            caption={T.tabs.claim.recommended}
            columns={columns}
            rows={list.data.items}
            rowKey={(r) => r.id}
            onRowClick={(rec) => onOpen({ kind: "recommended", rec })}
            rowLabel={(r) => T.claim.openRow(r.case.case_no_text || r.case.ref_no)}
            empty={<EmptyState title={T.inbox.nothingWaiting}>{T.inbox.empty}</EmptyState>}
          />
          <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
        </>
      ) : null}
    </section>
  );
}
