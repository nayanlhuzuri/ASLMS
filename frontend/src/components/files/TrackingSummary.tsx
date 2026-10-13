"use client";

/**
 * The tracking summary of the Department files tab (design portal-files-alerts, decision 12): per tracked department,
 * tiles held / due soon / overdue, then counts by holder department and by holder. Counts only, as the API gives them.
 */
import { useQuery } from "@tanstack/react-query";

import { ErrorBanner, Loading, numCell, Table, Tile } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CustodySummary, DepartmentCustodySummary } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./files.module.css";

export const TRACK_ERRORS = { forbidden: () => T.files.notTracking };

function CountCells({ row }: { row: { held: number; due_soon: number; overdue: number } }) {
  return (
    <>
      <td className={numCell}>{formatNumber(row.held)}</td>
      <td className={numCell}>{formatNumber(row.due_soon)}</td>
      <td className={numCell}>{formatNumber(row.overdue)}</td>
    </>
  );
}

function CountHeads() {
  return (
    <>
      <th scope="col" className={numCell}>
        {T.files.held}
      </th>
      <th scope="col" className={numCell}>
        {T.files.dueSoon}
      </th>
      <th scope="col" className={numCell}>
        {T.files.overdue}
      </th>
    </>
  );
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
        <Table caption={T.files.byHolderDepartment}>
          <thead>
            <tr>
              <th scope="col">{T.files.department}</th>
              <CountHeads />
            </tr>
          </thead>
          <tbody>
            {d.by_holder_department.map((r) => (
              <tr key={r.code}>
                <td className="mono">{r.code}</td>
                <CountCells row={r} />
              </tr>
            ))}
          </tbody>
        </Table>
        <Table caption={T.files.byHolder}>
          <thead>
            <tr>
              <th scope="col">{T.files.office}</th>
              <th scope="col">{T.files.officer}</th>
              <th scope="col">{T.files.designation}</th>
              <CountHeads />
            </tr>
          </thead>
          <tbody>
            {d.by_holder.map((r, i) => (
              <tr key={`${r.office_code}-${r.user_name ?? ""}-${i}`}>
                <td className="mono">{r.office_code}</td>
                <td>{r.user_name ?? "—"}</td>
                <td>{r.designation ?? "—"}</td>
                <CountCells row={r} />
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </section>
  );
}

export function TrackingSummary() {
  const summary = useQuery({
    queryKey: ["files", "summary"],
    queryFn: () => api<CustodySummary>("/custody/summary"),
  });
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
