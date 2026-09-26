"use client";

import { apiUrl, type Query } from "@/lib/api";
import { fmtDate, fmtNumber, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReportTable } from "@/lib/types";
import { Button, LinkButton } from "../ui/Button";
import { Card, CardHead } from "../ui/Layout";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";

const HEADERS: Record<string, string> = {
  under_1y: "Under 1 year",
  "1_to_5y": "1 to 5 years",
  over_5y: "Over 5 years",
  open_alerts: "Open actions",
  cases_heard: "Cases heard",
  case_type: "Case type",
};

const MONO = new Set(["department", "office", "code", "case_type"]);

function cell(key: string, v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (typeof v === "number") return fmtNumber(v);
  if (typeof v === "string") return key === "date" ? fmtDate(v) : v;
  return String(v);
}

export function ReportExport({ path, query }: { path: string; query?: Query }) {
  return (
    <span className="no-print" style={{ display: "inline-flex", gap: 8, flexWrap: "wrap" }}>
      <LinkButton href={apiUrl(path, { ...query, format: "xlsx" })} external small icon="download">
        Export Excel
      </LinkButton>
      <LinkButton href={apiUrl(path, { ...query, format: "csv" })} external small icon="download">
        CSV
      </LinkButton>
      <Button small icon="printer" onClick={() => window.print()}>
        Print
      </Button>
    </span>
  );
}

/** A tabular report from GET /reports/{name}, with Excel / CSV export and a print layout. */
export function ReportView({ path, query, empty }: { path: string; query?: Query; empty: string }) {
  const state = useApi<ReportTable>(path, query);
  return (
    <Card>
      <Async state={state} loadingLabel="Preparing the report">
        {(r) => {
          const keys = r.rows.length ? Object.keys(r.rows[0]) : [];
          return (
            <>
              <CardHead title={r.title} actions={<ReportExport path={path} query={query} />} />
              {r.rows.length === 0 ? (
                <Empty title={empty} />
              ) : (
                <DataTable
                  bare
                  caption={r.title}
                  rows={r.rows}
                  rowKey={(_, i) => String(i)}
                  columns={keys.map((k) => ({
                    key: k,
                    header: HEADERS[k] ?? humanize(k),
                    num: typeof r.rows[0][k] === "number",
                    mono: MONO.has(k),
                    render: (row: Record<string, unknown>) => cell(k, row[k]),
                  }))}
                />
              )}
            </>
          );
        }}
      </Async>
    </Card>
  );
}
