"use client";

/**
 * The charts and the accountability section of Insights (design state-insights, decisions 21 to 23 and 31), loaded by
 * the page through `next/dynamic` with `ssr: false`, so Recharts reaches no other route. Every chart counts with every
 * filter except its own dimension (the server does it); a bar sets its dimension's filter and a click on the selected
 * bar removes it. "View as Table" shows the same numbers with a filter button on every row, the keyboard path of every
 * click. The department bands are drawn side by side and never added together.
 */
import { useState, type ReactNode } from "react";

import { Button, type Column, DataTable, numCell } from "@/components/ui";
import {
  ChartCard,
  GroupedBarChart,
  hearingColour,
  HBarChart,
  StackedBarChart,
  TrendChart,
  type BarDatum,
  type MultiRow,
} from "@/components/ui/insightCharts";
import type { InsightsBucket, InsightsOverview } from "@/lib/api/types";
import { serverLabel } from "@/lib/displayLabels";
import { formatMonthYear, formatNumber } from "@/lib/format";
import {
  bandToggled,
  BANDS,
  holderToggled,
  statusOf,
  tickLabel,
  toggled,
  TOP_COUNSEL,
  TOP_DEPARTMENTS,
  TOP_KINDS,
  topRows,
  trendClicked,
  type Band,
  type DimensionKey,
} from "@/lib/insights";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import s from "./insights.module.css";

type Change = (next: Params) => void;

const C = T.insights.charts;

/** A server bucket list as bars; `labels` false keeps the label as sent (counsel codes are data, not labels). */
function bars(buckets: readonly InsightsBucket[], labels = true): BarDatum[] {
  return buckets.map((b) => ({ key: b.key, label: labels ? serverLabel(b.label) : b.label, count: b.count }));
}

/** One row's filter button: Filter, or Remove Filter on the selected row, each naming its value. */
function FilterButton({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <Button
      variant={selected ? "secondary" : "ghost"}
      size="sm"
      aria-pressed={selected}
      aria-label={selected ? C.removeAria(label) : C.filterAria(label)}
      onClick={onClick}
    >
      {selected ? C.removeButton : C.filterButton}
    </Button>
  );
}

/** "View as Table" of a one-dimension chart: the value (with its tick when selected), the cases and the filter button. */
export function BucketTable({
  caption,
  rows,
  selected,
  onSelect,
  header = C.cols.bucket,
}: {
  caption: string;
  rows: readonly BarDatum[];
  selected?: string | null;
  onSelect?: (key: string) => void;
  header?: string;
}) {
  const columns: Column<BarDatum>[] = [
    { key: "label", header, primary: true, rowHeader: true, cell: (r) => tickLabel(r.label, r.key === selected) },
    { key: "count", header: C.cols.cases, align: "right", cell: (r) => <span className={numCell}>{formatNumber(r.count)}</span> },
  ];
  if (onSelect) {
    columns.push({
      key: "filter",
      header: <span className="visually-hidden">{C.cols.filter}</span>,
      label: C.cols.filter,
      actions: true,
      align: "right",
      cell: (r) => <FilterButton label={r.label} selected={r.key === selected} onClick={() => onSelect(r.key)} />,
    });
  }
  return <DataTable caption={caption} rows={[...rows]} rowKey={(r) => r.key} columns={columns} />;
}

/** A card with a one-dimension bar chart, its table and an optional Show All. */
function BarCard({
  title,
  coverage,
  note,
  rows,
  selected,
  onSelect,
  colourOf,
  limit,
  wide,
}: {
  title: string;
  coverage: string;
  note?: ReactNode;
  rows: BarDatum[];
  selected?: string | null;
  onSelect?: (key: string) => void;
  colourOf?: Parameters<typeof HBarChart>[0]["colourOf"];
  limit?: number;
  wide?: boolean;
}) {
  const [all, setAll] = useState(false);
  const shown = limit ? topRows(rows, limit, all) : rows;
  const empty = rows.every((r) => r.count === 0);
  return (
    <div className={wide ? s.wide : s.cell}>
      <ChartCard
        title={title}
        coverage={coverage}
        empty={empty}
        actions={
          limit && rows.length > limit ? (
            <Button variant="ghost" aria-expanded={all} onClick={() => setAll((v) => !v)}>
              {all ? C.showTopButton(limit) : C.showAllButton}
            </Button>
          ) : null
        }
        table={<BucketTable caption={title} rows={shown} selected={selected} onSelect={onSelect} />}
      >
        {note ? <p className={s.notes}>{note}</p> : null}
        <HBarChart title={title} data={shown} selected={selected} onSelect={onSelect} colourOf={colourOf} />
      </ChartCard>
    </div>
  );
}

export function InsightsCharts({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const coverage = data.coverage.line;
  const pick = (key: DimensionKey) => (value: string) => onChange(toggled(params, key, value));
  const status = statusOf(params);
  const ageTitle = status === "pending" ? C.agePending : status === "disposed" ? C.ageDisposed : C.ageAll;
  const state = data.scope.kind === "state";
  return (
    <>
      <section className={s.section} aria-label={C.heading}>
        <div className={s.grid}>
          <div className={s.gridInner}>
            <KindByAge data={data} params={params} onChange={onChange} />
            <BarCard title={C.next} coverage={coverage} rows={bars(data.next_hearing)} selected={params.next} onSelect={pick("next")} colourOf={hearingColour} />
            <BarCard title={ageTitle} coverage={coverage} rows={bars(data.age)} selected={params.age} onSelect={pick("age")} />
            <BarCard title={C.filed} coverage={coverage} rows={bars(data.filed)} selected={params.filed} onSelect={pick("filed")} />
            {state ? <Departments data={data} params={params} onChange={onChange} /> : <Units data={data} params={params} onChange={onChange} />}
            <BarCard
              title={C.posts}
              coverage={coverage}
              note={T.insights.chartNotes.postsNote}
              rows={bars(data.posts)}
              selected={params.post}
              onSelect={pick("post")}
            />
            <BarCard title={C.subjects} coverage={coverage} rows={bars(data.subjects)} selected={params.subject} onSelect={pick("subject")} />
            <BarCard
              title={C.counsel}
              coverage={coverage}
              note={T.insights.chartNotes.counselNote}
              rows={bars(data.counsel, false)}
              selected={params.counsel}
              onSelect={pick("counsel")}
              limit={TOP_COUNSEL}
            />
            <Trend data={data} params={params} onChange={onChange} />
            <BarCard
              title={C.outcomes}
              coverage={coverage}
              note={T.insights.chartNotes.outcomesNote}
              rows={bars(data.outcomes)}
              selected={params.outcome}
              onSelect={pick("outcome")}
            />
          </div>
        </div>
      </section>
      <Accountability data={data} params={params} onChange={onChange} />
    </>
  );
}

/** Kind of case × age band (decision 22): top 10 kinds with Show All; a click on a kind sets it. */
function KindByAge({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const [all, setAll] = useState(false);
  const series = data.kind_by_age.bands.map((b) => ({ key: b.key, label: serverLabel(b.label) }));
  const rows: MultiRow[] = data.kind_by_age.rows.map((r) => ({ key: r.key, label: serverLabel(r.label), values: r.by_age }));
  const shown = topRows(rows, TOP_KINDS, all);
  const totals = new Map(data.kind_by_age.rows.map((r) => [r.key, r.total]));
  const empty = data.kind_by_age.rows.every((r) => r.total === 0);
  const select = (key: string) => onChange(toggled(params, "kind", key));
  const columns: Column<MultiRow>[] = [
    { key: "kind", header: C.cols.kind, primary: true, rowHeader: true, cell: (r) => tickLabel(r.label, r.key === params.kind) },
    { key: "total", header: C.cols.total, align: "right", cell: (r) => <span className={numCell}>{formatNumber(totals.get(r.key) ?? 0)}</span> },
    ...series.map(
      (sd): Column<MultiRow> => ({
        key: sd.key,
        header: sd.label,
        align: "right",
        cell: (r) => <span className={numCell}>{formatNumber(r.values[sd.key] ?? 0)}</span>,
      }),
    ),
    {
      key: "filter",
      header: <span className="visually-hidden">{C.cols.filter}</span>,
      label: C.cols.filter,
      actions: true,
      align: "right",
      cell: (r) => <FilterButton label={r.label} selected={r.key === params.kind} onClick={() => select(r.key)} />,
    },
  ];
  return (
    <div className={s.wide}>
      <ChartCard
        title={C.kindAge}
        coverage={data.coverage.line}
        empty={empty}
        actions={
          rows.length > TOP_KINDS ? (
            <Button variant="ghost" aria-expanded={all} onClick={() => setAll((v) => !v)}>
              {all ? C.showTopButton(TOP_KINDS) : C.showAllButton}
            </Button>
          ) : null
        }
        table={<DataTable caption={C.kindAge} rows={shown} rowKey={(r) => r.key} columns={columns} />}
      >
        <StackedBarChart title={C.kindAge} rows={shown} series={series} selected={params.kind} onSelect={select} />
      </ChartCard>
    </div>
  );
}

/** By Department (State scope, decision 21): three bands side by side, top 15 by their largest band, Show All. */
function Departments({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const [all, setAll] = useState(false);
  const series = BANDS.map((b) => ({ key: b, label: T.insights.bands[b]! }));
  const rows: MultiRow[] = (data.departments ?? []).map((d) => ({
    key: d.code,
    label: d.name,
    values: { claimed: d.claimed, likely: d.likely, named: d.named },
  }));
  const shown = topRows(rows, TOP_DEPARTMENTS, all);
  const empty = rows.every((r) => BANDS.every((b) => (r.values[b] ?? 0) === 0));
  const selected = params.dept ? { row: params.dept, series: params.band ?? null } : null;
  const select = (dept: string, band: string) => onChange(bandToggled(params, dept, band as Band));
  const columns: Column<MultiRow>[] = [
    { key: "department", header: C.cols.department, primary: true, rowHeader: true, cell: (r) => tickLabel(r.label, r.key === params.dept) },
    ...series.map(
      (sd): Column<MultiRow> => ({
        key: sd.key,
        header: sd.label,
        align: "right",
        cell: (r) => {
          const on = params.dept === r.key && params.band === sd.key;
          return (
            <Button
              variant={on ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={on}
              aria-label={on ? C.removeAria(`${r.label} · ${sd.label}`) : C.filterAria(`${r.label} · ${sd.label}`)}
              onClick={() => select(r.key, sd.key)}
            >
              {formatNumber(r.values[sd.key] ?? 0)}
            </Button>
          );
        },
      }),
    ),
  ];
  return (
    <div className={s.wide}>
      <ChartCard
        title={C.byDepartment}
        coverage={data.coverage.line}
        empty={empty}
        actions={
          rows.length > TOP_DEPARTMENTS ? (
            <Button variant="ghost" aria-expanded={all} onClick={() => setAll((v) => !v)}>
              {all ? C.showTopButton(TOP_DEPARTMENTS) : C.showAllButton}
            </Button>
          ) : null
        }
        table={<DataTable caption={C.byDepartment} rows={shown} rowKey={(r) => r.key} columns={columns} />}
      >
        <p className={s.notes}>{T.insights.chartNotes.departmentsNote(data.unmapped_named)}</p>
        <GroupedBarChart title={C.byDepartment} rows={shown} series={series} selected={selected} onSelect={select} />
      </ChartCard>
    </div>
  );
}

/**
 * By Unit (department scope, decision 22): claimed cases by assigned unit, plus the department's three band totals as
 * words (a department filter is refused outside the State scope, so these are not clickable).
 */
function Units({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const rows: BarDatum[] = (data.units ?? []).map((u) => ({ key: u.code, label: u.name, count: u.claimed }));
  const b = data.department_bands;
  return (
    <BarCard
      title={C.byUnit}
      coverage={data.coverage.line}
      wide
      note={
        <>
          <span>{T.insights.chartNotes.unitsNote}</span>
          {b ? (
            <span className={s.bandLine}>
              <span>{T.insights.chartNotes.departmentBandsNote}</span>
              {BANDS.map((k) => (
                <span key={k}>
                  {T.insights.bands[k]}: <strong>{formatNumber(b[k])}</strong>
                </span>
              ))}
            </span>
          ) : null}
        </>
      }
      rows={rows}
      selected={params.unit}
      onSelect={(key) => onChange(toggled(params, "unit", key))}
    />
  );
}

/** Is the Backlog Growing? (decision 22): registrations against disposals by IST month; a month sets Date Of. */
function Trend({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const rows = data.trend.map((t) => ({ key: t.month, label: formatMonthYear(`${t.month}-01`), a: t.registered, b: t.disposed }));
  const empty = rows.every((r) => r.a === 0 && r.b === 0);
  const columns: Column<(typeof rows)[number]>[] = [
    { key: "month", header: C.cols.month, primary: true, rowHeader: true, cell: (r) => r.label },
    ...(["registration", "disposal"] as const).map(
      (which): Column<(typeof rows)[number]> => ({
        key: which,
        header: which === "registration" ? C.cols.registered : C.cols.disposed,
        align: "right",
        cell: (r) => {
          const n = which === "registration" ? r.a : r.b;
          const words = `${r.label} · ${which === "registration" ? C.registeredLabel : C.disposedLabel}`;
          const on = params.date_of === which && params.from === `${r.key}-01` && (params.to ?? "").startsWith(r.key);
          return (
            <Button
              variant={on ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={on}
              aria-label={on ? C.removeAria(words) : C.filterAria(words)}
              onClick={() => onChange(trendClicked(params, r.key, which))}
            >
              {formatNumber(n)}
            </Button>
          );
        },
      }),
    ),
  ];
  return (
    <div className={s.wide}>
      <ChartCard
        title={C.trend}
        coverage={data.coverage.line}
        empty={empty}
        table={<DataTable caption={C.trend} rows={rows} rowKey={(r) => r.key} columns={columns} />}
      >
        <p className={s.notes}>{T.insights.chartNotes.trendNote}</p>
        <TrendChart
          title={C.trend}
          data={rows}
          aLabel={C.registeredLabel}
          bLabel={C.disposedLabel}
          onSelect={(month) => onChange(trendClicked(params, month, "registration"))}
        />
      </ChartCard>
    </div>
  );
}

const A = T.insights.accountability;

/** The accountability section (decision 23): action status, compliance, who is holding cases and the scorecard. */
function Accountability({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const acc = data.accountability;
  const coverage = data.coverage.line;
  const state = data.scope.kind === "state";
  const holders: BarDatum[] = acc.holders.map((h) => ({ key: h.code, label: h.name, count: h.overdue }));
  return (
    <section className={s.section} aria-labelledby="insights-accountability">
      <h2 id="insights-accountability">{A.heading}</h2>
      <div className={s.grid}>
        <div className={s.gridInner}>
          <BarCard
            title={A.action}
            coverage={coverage}
            rows={bars(acc.action)}
            selected={params.action}
            onSelect={(key) => onChange(toggled(params, "action", key))}
          />
          <Compliance data={data} params={params} onChange={onChange} />
          <BarCard
            title={A.holders}
            coverage={coverage}
            note={A.holdersNote}
            rows={holders}
            selected={params.holder}
            onSelect={(key) => onChange(holderToggled(params, key))}
          />
          {state && acc.scorecard ? <Scorecard data={data} params={params} onChange={onChange} /> : null}
        </div>
      </div>
    </section>
  );
}

/**
 * Compliance With Court Directions by owning department (decision 23): overdue and due soon side by side. A bar sets
 * the compliance filter; in the State scope it also sets that department as owner (`dept` with band Claimed).
 */
function Compliance({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const state = data.scope.kind === "state";
  const series = [
    { key: "overdue", label: A.overdueLabel },
    { key: "due_soon", label: A.dueSoonLabel },
  ];
  const rows: MultiRow[] = data.accountability.compliance.map((c) => ({
    key: c.code,
    label: c.name,
    values: { overdue: c.overdue, due_soon: c.due_soon },
  }));
  const selectedRow = params.compliance ? (state ? params.dept ?? null : null) : null;
  function select(dept: string, which: string) {
    if (!state) {
      onChange(toggled(params, "compliance", which));
      return;
    }
    const same = params.compliance === which && params.dept === dept && params.band === "claimed";
    const next = { ...bandToggled(params, dept, "claimed") };
    if (same) delete next.compliance;
    else next.compliance = which;
    onChange(next);
  }
  const columns: Column<MultiRow>[] = [
    { key: "department", header: C.cols.department, primary: true, rowHeader: true, cell: (r) => tickLabel(r.label, r.key === selectedRow) },
    ...series.map(
      (sd): Column<MultiRow> => ({
        key: sd.key,
        header: sd.label,
        align: "right",
        cell: (r) => {
          const on = params.compliance === sd.key && (!state || params.dept === r.key);
          const words = `${r.label} · ${sd.label}`;
          return (
            <Button
              variant={on ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={on}
              aria-label={on ? C.removeAria(words) : C.filterAria(words)}
              onClick={() => select(r.key, sd.key)}
            >
              {formatNumber(r.values[sd.key] ?? 0)}
            </Button>
          );
        },
      }),
    ),
  ];
  return (
    <div className={s.cell}>
      <ChartCard
        title={A.compliance}
        coverage={data.coverage.line}
        empty={rows.length === 0}
        table={<DataTable caption={A.compliance} rows={rows} rowKey={(r) => r.key} columns={columns} />}
      >
        <p className={s.notes}>{A.complianceNote}</p>
        <GroupedBarChart
          title={A.compliance}
          rows={rows}
          series={series}
          selected={selectedRow ? { row: selectedRow, series: params.compliance ?? null } : null}
          onSelect={select}
        />
      </ChartCard>
    </div>
  );
}

function numberCell(n: number): ReactNode {
  return <span className={numCell}>{formatNumber(n)}</span>;
}

type ScoreRow = NonNullable<InsightsOverview["accountability"]["scorecard"]>[number];

/** The Department Scorecard (decision 23, State scope only): no column adds bands together. */
function Scorecard({ data, params, onChange }: { data: InsightsOverview; params: Params; onChange: Change }) {
  const rows = data.accountability.scorecard ?? [];
  const sc = A.scorecardCols;
  const num = (pick: (r: ScoreRow) => number) => (r: ScoreRow) => numberCell(pick(r));
  const columns: Column<ScoreRow>[] = [
    // the name is text and the filter its own row button (as in View As Table), so a long department name wraps in its
    // cell and never runs a button past the card on a phone (row 259 tester finding)
    {
      key: "department",
      header: sc.department,
      primary: true,
      rowHeader: true,
      cell: (r) => tickLabel(r.name, params.dept === r.code && !params.band),
    },
    { key: "claimed", header: sc.claimed, align: "right", cell: num((r) => r.claimed) },
    { key: "likely", header: sc.likely, align: "right", cell: num((r) => r.likely) },
    { key: "named", header: sc.named, align: "right", cell: num((r) => r.named_only) },
    { key: "contempt", header: sc.contempt, align: "right", cell: num((r) => r.contempt_claimed) },
    { key: "hearing", header: sc.hearing, align: "right", cell: num((r) => r.hearing_7_days) },
    { key: "overdue", header: sc.overdue, align: "right", cell: num((r) => r.overdue_actions) },
    { key: "compliance", header: sc.compliance, align: "right", cell: num((r) => r.compliance_overdue) },
    {
      key: "median",
      header: sc.median,
      align: "right",
      cell: (r) => <span className={numCell}>{r.median_days_to_claim === null || r.median_days_to_claim === undefined ? "—" : formatNumber(Math.round(r.median_days_to_claim))}</span>,
    },
    {
      key: "filter",
      header: <span className="visually-hidden">{C.cols.filter}</span>,
      label: C.cols.filter,
      actions: true,
      align: "right",
      cell: (r) => (
        <FilterButton label={r.name} selected={params.dept === r.code && !params.band} onClick={() => onChange(bandToggled(params, r.code, null))} />
      ),
    },
  ];
  return (
    <div className={s.wide}>
      <section className={s.section} aria-labelledby="insights-scorecard">
        <h3 id="insights-scorecard">{A.scorecard}</h3>
        <p className={s.notes}>{A.scorecardNote}</p>
        <DataTable caption={A.scorecard} rows={rows} rowKey={(r) => r.code} columns={columns} />
      </section>
    </div>
  );
}
