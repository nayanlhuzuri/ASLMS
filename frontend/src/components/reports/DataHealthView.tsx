"use client";

import { useState } from "react";
import { fmtDate, fmtDateTime, fmtNumber, fmtPercent, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { sourceLabel } from "@/lib/labels";
import type { DataHealth } from "@/lib/types";
import { Button } from "../ui/Button";
import { Field, Select } from "../ui/Field";
import { Card, CardHead, Kpi, KpiRow } from "../ui/Layout";
import { Pill } from "../ui/Pill";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";

/** Job counters, flattened one level ("delivery: email sent 1"); zero counts are left out. */
function counters(c: Record<string, unknown> | null): string {
  if (!c) return "-";
  const parts: string[] = [];
  const add = (label: string, v: unknown) => {
    if (typeof v === "number" && v !== 0) parts.push(`${label} ${fmtNumber(v)}`);
    else if (typeof v === "string" && v) parts.push(`${label}: ${v}`);
  };
  for (const [k, v] of Object.entries(c)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) add(`${humanize(k)}: ${k2.replace(/_/g, " ")}`, v2);
    } else add(humanize(k), v);
  }
  return parts.slice(0, 8).join(" · ") || "No counts";
}

export function DataHealthView() {
  const [days, setDays] = useState(7);
  const state = useApi<DataHealth>("/reports/data-health", { days });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }} className="no-print">
        <Field label="Period">
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </Select>
        </Field>
        <Button small icon="printer" onClick={() => window.print()}>
          Print
        </Button>
      </div>
      <Async state={state} loadingLabel="Checking data collection">
        {(h) => {
          const calls = h.napix_calls.reduce((a, c) => a + c.calls, 0);
          const ok = h.napix_calls.reduce((a, c) => a + c.ok, 0);
          const failedJobs = h.jobs.filter((j) => j.status === "failed").length;
          const entries = h.entries_by_source.reduce((a, e) => a + e.entries, 0);
          const withCnr = h.entries_by_source.reduce((a, e) => a + e.with_cnr, 0);
          return (
            <>
              <KpiRow>
                <Kpi label="Jobs run" value={fmtNumber(h.jobs.length)} tone={failedJobs ? "critical" : undefined} note={`${fmtNumber(failedJobs)} failed`} />
                <Kpi label="NAPIX calls" value={fmtNumber(calls)} tone="accent" note={calls ? `${fmtPercent(ok / calls)} succeeded` : "no calls in the period"} />
                <Kpi label="Open failures" value={fmtNumber(h.open_failures.length)} tone={h.open_failures.length ? "warning" : undefined} note="waiting for retry or review" />
                <Kpi label="CNR rate" value={entries ? fmtPercent(withCnr / entries) : "-"} note={`${fmtNumber(withCnr)} of ${fmtNumber(entries)} entries resolved to a CNR`} />
              </KpiRow>
              <Card>
                <CardHead title="Jobs" />
                {h.jobs.length === 0 ? (
                  <Empty title="No job ran in the period" />
                ) : (
                  <DataTable
                    bare
                    caption="Jobs"
                    rows={h.jobs}
                    rowKey={(j, i) => `${j.job}-${j.started_at}-${i}`}
                    columns={[
                      { key: "job", header: "Job", render: (j) => humanize(j.job) },
                      { key: "date", header: "For date", render: (j) => fmtDate(j.run_date) },
                      {
                        key: "status",
                        header: "Status",
                        render: (j) => <Pill tone={j.status === "succeeded" || j.status === "ok" || j.status === "done" ? "success" : j.status === "failed" ? "criticalSoft" : "warning"}>{humanize(j.status)}</Pill>,
                      },
                      { key: "start", header: "Started", render: (j) => fmtDateTime(j.started_at) },
                      { key: "end", header: "Finished", render: (j) => fmtDateTime(j.finished_at) },
                      { key: "counters", header: "Counts", render: (j) => <span style={{ fontSize: 13 }}>{j.error ? <span style={{ color: "var(--critical)" }}>{j.error}</span> : counters(j.counters)}</span> },
                    ]}
                  />
                )}
              </Card>
              <Card>
                <CardHead title="NAPIX calls" />
                {h.napix_calls.length === 0 ? (
                  <Empty title="No NAPIX call in the period" />
                ) : (
                  <DataTable
                    bare
                    caption="NAPIX calls"
                    rows={h.napix_calls}
                    rowKey={(c) => c.api}
                    columns={[
                      { key: "api", header: "API", mono: true, render: (c) => c.api },
                      { key: "calls", header: "Calls", num: true, render: (c) => fmtNumber(c.calls) },
                      { key: "ok", header: "Succeeded", num: true, render: (c) => fmtNumber(c.ok) },
                      { key: "rate", header: "Success rate", num: true, render: (c) => (c.calls ? fmtPercent(c.ok / c.calls) : "-") },
                      { key: "ms", header: "Average time", num: true, render: (c) => `${fmtNumber(c.avg_ms)} ms` },
                    ]}
                  />
                )}
              </Card>
              <Card>
                <CardHead title="Open failures" />
                {h.open_failures.length === 0 ? (
                  <Empty title="No open failures" />
                ) : (
                  <DataTable
                    bare
                    caption="Open failures"
                    rows={h.open_failures}
                    rowKey={(f) => f.id}
                    columns={[
                      { key: "kind", header: "Kind", render: (f) => humanize(f.kind) },
                      { key: "ref", header: "Reference", mono: true, render: (f) => f.ref },
                      { key: "error", header: "Error", render: (f) => <span style={{ fontSize: 13 }}>{f.error}</span> },
                      { key: "attempts", header: "Attempts", num: true, render: (f) => fmtNumber(f.attempts) },
                      { key: "last", header: "Last seen", render: (f) => fmtDateTime(f.last_seen) },
                    ]}
                  />
                )}
              </Card>
              <div style={{ display: "grid", gap: 18, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))" }}>
                <Card>
                  <CardHead title="Cause lists by source" />
                  {h.cause_lists.length === 0 ? (
                    <Empty title="No cause lists in the period" />
                  ) : (
                    <DataTable
                      bare
                      caption="Cause lists by source"
                      rows={h.cause_lists}
                      rowKey={(r, i) => `${r.date}-${r.source}-${i}`}
                      columns={[
                        { key: "date", header: "Date", render: (r) => fmtDate(r.date) },
                        { key: "source", header: "Source", render: (r) => sourceLabel(r.source) },
                        { key: "lists", header: "Lists", num: true, render: (r) => fmtNumber(r.lists) },
                        { key: "entries", header: "Entries", num: true, render: (r) => fmtNumber(r.entries) },
                      ]}
                    />
                  )}
                </Card>
                <Card>
                  <CardHead title="Entries and CNR rate" />
                  {h.entries_by_source.length === 0 ? (
                    <Empty title="No entries in the period" />
                  ) : (
                    <DataTable
                      bare
                      caption="Entries by source"
                      rows={h.entries_by_source}
                      rowKey={(r) => r.source}
                      columns={[
                        { key: "source", header: "Source", render: (r) => sourceLabel(r.source) },
                        { key: "entries", header: "Entries", num: true, render: (r) => fmtNumber(r.entries) },
                        { key: "cnr", header: "With CNR", num: true, render: (r) => fmtNumber(r.with_cnr) },
                        { key: "rate", header: "CNR rate", num: true, render: (r) => fmtPercent(r.cnr_rate) },
                      ]}
                    />
                  )}
                  {Object.keys(h.orders).length ? (
                    <p className="muted" style={{ fontSize: 13 }}>
                      Orders: {Object.entries(h.orders).map(([k, v]) => `${humanize(k)} ${fmtNumber(v)}`).join(" · ")}
                    </p>
                  ) : null}
                </Card>
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}
