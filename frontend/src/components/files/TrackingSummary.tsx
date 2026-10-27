"use client";

/**
 * The tracking summary of the Department files tab (design portal-files-alerts, decision 12): per tracked department,
 * tiles held / due soon / overdue, then counts by holder department and by holder. Counts only, as the API gives them.
 */
import { useQuery } from "@tanstack/react-query";

import { DataTable, ErrorBanner, Loading, Tile, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CustodySummary, DepartmentCustodySummary } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./files.module.css";

export const TRACK_ERRORS = { forbidden: () => T.files.notTracking };

type Counts = { held: number; due_soon: number; overdue: number };

/** The three count columns shared by both tables. */
function countColumns<Row extends Counts>(): Column<Row>[] {
  return [
    { key: "held", header: T.files.held, align: "right", cell: (r) => formatNumber(r.held) },
    { key: "due_soon", header: T.files.dueSoon, align: "right", cell: (r) => formatNumber(r.due_soon) },
    { key: "overdue", header: T.files.overdue, align: "right", cell: (r) => formatNumber(r.overdue) },
  ];
}

export function DepartmentSummary({ d }: { d: DepartmentCustodySummary }) {
  const title = T.files.summary(d.code);
  return (
    <section className={s.summary} aria-label={title}>
      <h2>{title}</h2>
      <div className={s.tiles}>
        <Tile label={T.files.held} value={d.held} />
        <Tile label={T.files.dueSoon} value={d.due_soon} />
        <Tile label={T.files.overdue} value={d.overdue} />
      </div>
      <div className={s.columns}>
        <DataTable
          caption={T.files.byHolderDepartment}
          showCaption
          rows={d.by_holder_department}
          rowKey={(r) => r.code}
          columns={[
            { key: "department", header: T.files.department, primary: true, cell: (r) => <span className="mono">{r.code}</span> },
            ...countColumns<(typeof d.by_holder_department)[number]>(),
          ]}
        />
        <DataTable
          caption={T.files.byHolder}
          showCaption
          rows={d.by_holder.map((r, i) => ({ ...r, key: `${r.office_code}-${r.user_name ?? ""}-${i}` }))}
          rowKey={(r) => r.key}
          columns={[
            { key: "office", header: T.files.office, primary: true, cell: (r) => <span className="mono">{r.office_code}</span> },
            { key: "officer", header: T.files.officer, cell: (r) => r.user_name ?? "—" },
            { key: "designation", header: T.files.designation, cell: (r) => r.designation ?? "—" },
            ...countColumns<(typeof d.by_holder)[number] & { key: string }>(),
          ]}
        />
      </div>
    </section>
  );
}

/**
 * `GET /custody/summary`, shared by the tracking summary and the Pending action count of the Case inbox (design
 * case-inbox-merge, decision 10); `enabled` only for a login tracking a department, so no one else gets a 403.
 */
export function useCustodySummary(enabled = true) {
  return useQuery({
    queryKey: ["files", "summary"],
    queryFn: () => api<CustodySummary>("/custody/summary"),
    enabled,
  });
}

export function TrackingSummary() {
  const summary = useCustodySummary();
  if (summary.isPending) return <Loading />;
  if (summary.error) {
    return <ErrorBanner error={summary.error} onRetry={() => summary.refetch()} messages={TRACK_ERRORS} />;
  }
  return (
    <>
      {summary.data.departments.map((d) => (
        <DepartmentSummary key={d.code} d={d} />
      ))}
    </>
  );
}
