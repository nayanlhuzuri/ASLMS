"use client";

/**
 * One generic renderer for every report (design portal-reports, decision 7): the header and the sections are drawn
 * from the JSON alone, so a column added on the server appears without a portal change. Cells by `kind`; `null` as
 * "—"; the totals row in `<tfoot>`; the section note; the truncated line; wide tables in a keyboard-scrollable region
 * with a sticky first column. Rows that name a case (they carry `ref_no`, only cases the caller may open) link the
 * case number to the case page and are paged by 50 in the browser. Nothing beyond what the API sent is shown.
 */
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Notice, numCell, Pagination } from "@/components/ui";
import u from "@/components/ui/data.module.css";
import type { Report, ReportDepartment, ReportSection } from "@/lib/api/types";
import { formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { PAGE } from "@/lib/params";
import { casePath } from "@/lib/refs";
import { cellText, departmentLabel, periodText, scopeLabel } from "@/lib/reports";

import s from "./reports.module.css";

const NUMERIC = new Set(["int", "days"]);

export function ReportView({
  report,
  departments,
  holderNames,
  actions,
}: {
  report: Report;
  departments: readonly ReportDepartment[] | undefined;
  /** Names of every active department (the holder department may be any). */
  holderNames?: Record<string, string>;
  /** Shown under the header (the download links). */
  actions?: ReactNode;
}) {
  const p = report.params as Record<string, unknown>;
  const by = report.generated_by;
  const who = [by.name, by.designation, by.office_code].filter(Boolean).join(", ");
  const holder = typeof p.holder_department === "string" && p.holder_department ? p.holder_department : null;
  return (
    <div className="stack">
      <section className={s.header} aria-label={report.title}>
        <h2>{report.title}</h2>
        <ul className={s.facts}>
          <li>{T.reports.scopeLine(scopeLabel(report, departments))}</li>
          {p.from && p.to ? <li>{T.reports.periodLine(periodText(p.from, p.to))}</li> : null}
          {holder ? (
            <li>
              {T.reports.holderLine(
                holderNames?.[holder] ? `${holderNames[holder]} (${holder})` : departmentLabel(holder, departments),
              )}
            </li>
          ) : null}
          {p.include_cases === true ? <li>{T.reports.withFiles}</li> : null}
          <li>{T.reports.generatedAt(formatDateTime(report.generated_at))}</li>
          {who ? <li>{T.reports.generatedBy(who)}</li> : null}
        </ul>
        <Notice>{report.as_of_note}</Notice>
      </section>
      {actions}
      {report.sections.map((section) => (
        <SectionTable key={section.key} section={section} />
      ))}
    </div>
  );
}

function Cell({ row, column }: { row: Record<string, unknown>; column: { key: string; kind: string } }) {
  const value = row[column.key];
  const ref = typeof row.ref_no === "string" && row.ref_no ? row.ref_no : null;
  if (column.key === "case_no" && ref) {
    return (
      <Link href={casePath(ref)} className="mono" title={typeof row.cnr === "string" ? row.cnr : undefined}>
        {value === null || value === undefined || value === "" ? ref : String(value)}
      </Link>
    );
  }
  return <>{cellText(value, column.kind)}</>;
}

export function SectionTable({ section }: { section: ReportSection }) {
  const [offset, setOffset] = useState(0);
  const rows = section.rows as Record<string, unknown>[];
  const paged = rows.some((r) => typeof r.ref_no === "string");
  const shown = paged ? rows.slice(offset, offset + PAGE) : rows;
  const totals = section.totals as Record<string, unknown> | null;
  return (
    <div className="stack">
      {rows.length === 0 ? (
        <>
          <h3>{section.title}</h3>
          <p className="muted">{T.reports.emptySection}</p>
        </>
      ) : (
        <>
          <div className={s.scroll} role="region" aria-label={section.title} tabIndex={0}>
            <table className={u.table}>
              <caption>{section.title}</caption>
              <thead>
                <tr>
                  {section.columns.map((c) => (
                    <th key={c.key} scope="col" className={NUMERIC.has(c.kind) ? numCell : undefined}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((row, i) => (
                  <tr key={offset + i}>
                    {section.columns.map((c) => (
                      <td key={c.key} className={NUMERIC.has(c.kind) ? numCell : undefined}>
                        <Cell row={row} column={c} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {totals ? (
                <tfoot>
                  <tr className={s.totals}>
                    {section.columns.map((c) => {
                      const v = totals[c.key];
                      return (
                        <td key={c.key} className={NUMERIC.has(c.kind) ? numCell : undefined}>
                          {v === null || v === undefined || v === "" ? "" : cellText(v, c.kind)}
                        </td>
                      );
                    })}
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>
          {paged ? <Pagination offset={offset} limit={PAGE} total={rows.length} onChange={setOffset} /> : null}
        </>
      )}
      {section.note ? <p className="muted">{section.note}</p> : null}
      {section.truncated ? (
        <p>{T.reports.truncated(formatNumber(rows.length), formatNumber(section.total_rows))}</p>
      ) : null}
    </div>
  );
}
