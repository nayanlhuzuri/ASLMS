"use client";

/**
 * The Insights case list (design state-insights, decisions 26, 27 and 33): 20 cases a page of the selection, in its own
 * request so paging never counts the charts again, with the allow-listed sorts and Export Excel and Export PDF, which
 * open the export dialog. Who has each case is built on the server; the portal only names the offices through
 * `OfficeName`. Only cases of the scope the viewer may open come back, so every case number is a link.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  Button,
  CaseLink,
  type Column,
  DataTable,
  EmptyState,
  ErrorBanner,
  HearingDate,
  Loading,
  OfficeName,
  Pagination,
  SelectField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import type { InsightsCaseItem, InsightsCases } from "@/lib/api/types";
import { labelFor, serverLabel } from "@/lib/displayLabels";
import { CASE_PAGE_SIZE, CASE_SORTS, insightsParams, type ExportFormat } from "@/lib/insights";
import { INSIGHTS_ERRORS, T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";

import { ExportDialog } from "./ExportDialog";
import s from "./insights.module.css";

const L = T.insights.list;

export function pageOf(params: Params): number {
  const n = Number(params.page ?? 1);
  return Number.isInteger(n) && n > 0 ? n : 1;
}

/** "Yes (Parties, Counsel Code)" or "No" (decision 6), from the bases the server lists in order. */
export function stateWords(item: Pick<InsightsCaseItem, "state_case" | "state_basis">): string {
  if (!item.state_case || item.state_basis.length === 0) return L.stateNo;
  return L.stateYes(item.state_basis.map((b) => labelFor(T.insights.basis, b)).join(", "));
}

/** Who has the case (decision 26), the offices named through `OfficeName`; otherwise the server's own words. */
export function WhoHasIt({ who }: { who: InsightsCaseItem["who"] }) {
  const W = T.insights.who;
  switch (who.kind) {
    case "officer":
      return (
        <span>
          {W.withWord} {[who.officer_name, who.designation].filter(Boolean).join(", ")} · <OfficeName code={who.office_code} />
        </span>
      );
    case "office":
      return (
        <span>
          {W.withWord} <OfficeName code={who.office_code} /> · {W.notSent}
        </span>
      );
    case "closed":
      return (
        <span>
          {W.claimedBy} <OfficeName code={who.department_code} /> · {W.closed}
        </span>
      );
    case "claimed":
      return (
        <span>
          {W.claimedBy} <OfficeName code={who.department_code} />
        </span>
      );
    case "recommended":
      return (
        <span>
          {W.notClaimed} · {W.recommendedTo} <OfficeName code={who.recommended_to} />
          {who.more ? ` ${W.more(who.more)}` : null}
        </span>
      );
    default:
      return <span>{who.text}</span>;
  }
}

function NamedCell({ item }: { item: InsightsCaseItem }) {
  if (item.departments_named.length > 0) {
    return (
      <span>
        {item.departments_named.map((d, i) => (
          <span key={d.code}>
            {i > 0 ? "; " : null}
            <OfficeName code={d.code} name={d.name} />
          </span>
        ))}
      </span>
    );
  }
  if (item.phrases_unmapped.length > 0) return <span className="muted">{L.asRead(item.phrases_unmapped.join("; "))}</span>;
  return null;
}

export function CaseList({
  params,
  settledFilters,
  onChange,
}: {
  params: Params;
  /** The filters as the overview last asked (debounced), so the list follows the same selection. */
  settledFilters: string;
  onChange: (next: Params) => void;
}) {
  const page = pageOf(params);
  const sort = params.sort && (CASE_SORTS as readonly string[]).includes(params.sort) ? params.sort : "next";
  const extra = queryString({ page: page > 1 ? String(page) : undefined, sort: sort === "next" ? undefined : sort }).slice(1);
  const path = `/insights/cases${settledFilters}${extra ? (settledFilters ? "&" : "?") + extra : ""}`;
  const cases = useQuery({
    queryKey: ["insights", "cases", path],
    queryFn: ({ signal }) => api<InsightsCases>(path, { signal }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const data = cases.data;

  const columns: Column<InsightsCaseItem>[] = [
    {
      key: "case",
      header: L.cols.case,
      primary: true,
      cell: (r) => (
        <span>
          <CaseLink value={{ ref_no: r.case.ref_no, cnr: r.case.cnr, case_no_text: r.case.case_no }} />
          <span className={s.sub}>{L.stateCase(stateWords(r))}</span>
          {r.applications_pending ? <span className={s.sub}>{L.applications(r.applications_pending)}</span> : null}
        </span>
      ),
    },
    { key: "kind", header: L.cols.kind, cell: (r) => serverLabel(r.kind.label) },
    { key: "status", header: L.cols.status, cell: (r) => labelFor(T.insights.caseStatus, r.status) },
    { key: "who", header: L.cols.who, cell: (r) => <WhoHasIt who={r.who} /> },
    {
      key: "next",
      header: L.cols.next,
      cell: (r) => (
        <HearingDate date={r.next_hearing.on} status={r.status} kind={r.next_hearing.basis === "around" ? "around" : "firm"} />
      ),
    },
    { key: "named", header: L.cols.named, cell: (r) => <NamedCell item={r} /> },
  ];

  return (
    <section className={s.section} aria-labelledby="insights-cases">
      <div className={s.listHead}>
        <h2 id="insights-cases">{L.heading}</h2>
        <div className={s.listTools}>
          <SelectField
            label={L.sortLabel}
            options={CASE_SORTS.map((k) => ({ value: k, label: L.sorts[k]! }))}
            value={sort}
            onChange={(e) => {
              const next: Params = { ...params, sort: e.target.value === "next" ? undefined : e.target.value };
              delete next.page;
              onChange(next);
            }}
          />
          <div className={s.quick} role="group" aria-label={L.exportsLabel}>
            <Button variant="secondary" disabled={!data || data.total === 0} onClick={() => setExporting("xlsx")}>
              {L.exportXlsxButton}
            </Button>
            <Button variant="secondary" disabled={!data || data.total === 0} onClick={() => setExporting("pdf")}>
              {L.exportPdfButton}
            </Button>
          </div>
        </div>
      </div>
      {data ? <p className={s.notes}>{L.count(data.total)}</p> : null}
      {cases.error ? <ErrorBanner error={cases.error} messages={INSIGHTS_ERRORS} onRetry={() => void cases.refetch()} /> : null}
      {cases.isPending && !cases.error ? <Loading /> : null}
      {data ? (
        data.items.length === 0 ? (
          <EmptyState title={T.insights.emptyNote} />
        ) : (
          <>
            <DataTable caption={L.heading} rows={data.items} rowKey={(r) => r.case.id} columns={columns} />
            <Pagination
              offset={(page - 1) * CASE_PAGE_SIZE}
              limit={CASE_PAGE_SIZE}
              total={data.total}
              onChange={(offset) => onChange({ ...insightsParams(params), page: offset > 0 ? String(offset / CASE_PAGE_SIZE + 1) : undefined })}
            />
          </>
        )
      ) : null}
      {exporting && data ? (
        <ExportDialog
          format={exporting}
          params={{ ...params, sort: sort === "next" ? undefined : sort }}
          total={data.total}
          onClose={() => setExporting(null)}
        />
      ) : null}
    </section>
  );
}
