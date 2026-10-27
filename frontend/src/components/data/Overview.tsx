"use client";

/**
 * Overview, statistics only (design data-collection-redesign, decisions 14-21): the status line, four tiles with bars
 * (Cause Lists, Cases, Order PDFs, Still to Fetch) and the Waiting Work table, the Problems line, Right Now from the
 * pulse, the two-date estimate in words and Month by Month in its own scrolling box. Live by polling only while the
 * tab is visible: the pulse every 5 s, the overview every 30 s, the months every 120 s. No button changes anything
 * here; the page has no primary.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import {
  Badge,
  Button,
  Collapsible,
  DataTable,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  ProgressBar,
  ProgressLegend,
  ScrollBox,
  TabToolbar,
  useCountUp,
  useSecondsSince,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { Coverage, QueueList } from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import {
  causeListsLine,
  DC_KEYS,
  estimateInputs,
  estimateText,
  minutesToReset,
  monthLeft,
  monthName,
  monthProblems,
  monthTone,
  POLL,
  PROBLEM_LINKS,
  problemParts,
  type DataOverview,
  type DataPulse,
  type MonthRow,
} from "@/lib/dataCollection";
import { formatDate, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { COLLECT_FUNCTIONS } from "@/lib/routes";

import ds from "./data.module.css";

const n = (v: number | null | undefined) => formatNumber(v ?? 0);
const LANES = ["load", "daily", "discovery", "request"] as const;

export function useOverview() {
  return useQuery({
    queryKey: DC_KEYS.overview,
    queryFn: () => api<DataOverview>("/admin/data-load/overview"),
    refetchInterval: POLL.overview,
    refetchIntervalInBackground: false,
  });
}

export function usePulse(interval: number = POLL.pulse) {
  return useQuery({
    queryKey: DC_KEYS.pulse,
    queryFn: () => api<DataPulse>("/admin/data-load/pulse"),
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  });
}

export function Overview() {
  const me = useMe();
  const overview = useOverview();
  const pulse = usePulse();
  const months = useQuery({
    queryKey: DC_KEYS.months,
    queryFn: () => api<Coverage>("/admin/data-load/coverage"),
    refetchInterval: POLL.months,
    refetchIntervalInBackground: false,
  });
  const data = overview.data;
  return (
    <div className="stack">
      <TabToolbar updatedAt={overview.dataUpdatedAt || null}>
        {can(me.data, "reports.state") ? <Link href="/reports/data-health">{T.dc.reportLink}</Link> : null}
      </TabToolbar>
      <ErrorBanner error={overview.error} onRetry={() => overview.refetch()} />
      {overview.isPending ? <Loading lines={6} /> : null}
      {data ? (
        <>
          <StatusLine data={data} />
          <section className={ds.tiles} aria-label={T.dc.tilesLabel}>
            <CauseListsTile data={data} />
            <CasesTile data={data} />
            <OrdersTile data={data} />
            <LeftTile data={data} />
          </section>
          <ProblemsLine problems={data.problems} />
        </>
      ) : null}
      <RightNow pulse={pulse.data} fetchedAt={pulse.dataUpdatedAt} error={pulse.error} showCollect={canAny(me.data, COLLECT_FUNCTIONS)} />
      {data ? <EstimateCard data={data} /> : null}
      <MonthsCard
        data={months.data}
        pending={months.isPending}
        error={months.error}
        refetch={() => void months.refetch()}
        readsDays={canAny(me.data, ["reports.state", "admin.napix_refetch", "admin.masters_sync"])}
      />
    </div>
  );
}

function StatusLine({ data }: { data: DataOverview }) {
  const st = data.settings;
  const state = data.collection;
  return (
    <ul className={ds.statusLine} aria-label={T.dc.statusLabel}>
      <li>
        <b>{T.dc.connectionLabel}</b>
        <Badge tone={data.napix_enabled ? "success" : "warning"} title={T.dc.connectionTooltip}>
          {data.napix_enabled ? T.dc.connectionOn : T.dc.connectionOff}
        </Badge>
      </li>
      <li>
        <b>{T.dc.automaticLabel}</b>
        <span className={state === "running" ? ds.pulse : undefined}>
          <Badge
            tone={state === "running" ? "info" : state === "paused" ? "warning" : state === "finished" ? "success" : undefined}
            title={state === "paused" && st.reason ? st.reason : undefined}
          >
            {T.dc.states[state] ?? state}
          </Badge>
        </span>
      </li>
      {data.bulk ? (
        <li>
          <b>{T.dc.collectLabel}</b>
          <span>{T.dc.bulkLine(formatTime(String((data.bulk as Record<string, unknown>).expected_end ?? "")))}</span>
        </li>
      ) : null}
      <li>{data.period ? T.dc.periodLine(formatDate(data.period.from), formatDate(data.period.to)) : T.dc.noPeriodNote}</li>
    </ul>
  );
}

function Info({ text }: { text: string }) {
  return (
    <span className={ds.info} title={text} role="img" aria-label={text}>
      ?
    </span>
  );
}

function Tile({
  index,
  title,
  tooltip,
  big,
  children,
}: {
  index: number;
  title: string;
  tooltip: string;
  big: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className={`${ds.panel} ${ds.tile}`} style={{ ["--i" as string]: index }} aria-label={title}>
      <h2 className={ds.tileTitle}>
        {title} <Info text={tooltip} />
      </h2>
      <p className={ds.big}>{big}</p>
      {children}
    </article>
  );
}

/** A figure counting up (at once under reduced motion), with tabular figures. */
function Count({ value }: { value: number }) {
  return <>{formatNumber(useCountUp(value))}</>;
}

function CauseListsTile({ data }: { data: DataOverview }) {
  const d = data.days;
  const collected = useCountUp(d?.collected ?? 0);
  if (!d) {
    return (
      <Tile index={0} title={T.dc.causeListsTitle} tooltip={T.dc.causeListsTooltip} big="—">
        <p className={ds.line}>{T.dc.noPeriodNote}</p>
      </Tile>
    );
  }
  return (
    <Tile
      index={0}
      title={T.dc.causeListsTitle}
      tooltip={T.dc.causeListsTooltip}
      big={T.dc.causeListsBig(formatNumber(collected), n(d.calendar))}
    >
      <ProgressBar
        label={T.dc.causeListsTitle}
        max={d.calendar}
        segments={[
          { tone: "done", value: d.collected },
          { tone: "waiting", value: d.waiting },
          { tone: "failed", value: d.failed },
        ]}
        text={T.dc.barText.days(n(d.collected), n(d.calendar), n(d.waiting), n(d.failed))}
        showText={false}
      />
      <p className={ds.line}>{causeListsLine(data)}</p>
    </Tile>
  );
}

function CasesTile({ data }: { data: DataOverview }) {
  const c = data.cases;
  return (
    <Tile index={1} title={T.dc.casesTitle} tooltip={T.dc.casesTooltip} big={T.dc.casesBig(formatNumber(useCountUp(c.found)))}>
      <ProgressBar
        label={T.dc.casesTitle}
        max={c.found}
        segments={[
          { tone: "done", value: c.with_details },
          { tone: "waiting", value: c.without_details },
        ]}
        text={T.dc.barText.cases(n(c.with_details), n(c.found))}
        showText={false}
      />
      <p className={ds.line}>{T.dc.casesLine(n(c.with_details), n(c.without_details))}</p>
    </Tile>
  );
}

function OrdersTile({ data }: { data: DataOverview }) {
  const o = data.orders;
  const failed = o.failed ?? 0;
  return (
    <Tile
      index={2}
      title={T.dc.ordersTitle}
      tooltip={T.dc.ordersTooltip}
      big={T.dc.ordersBig(formatNumber(useCountUp(o.stored)), n(o.referenced))}
    >
      <ProgressBar
        label={T.dc.ordersTitle}
        max={o.referenced}
        segments={[
          { tone: "done", value: o.stored },
          { tone: "waiting", value: o.waiting },
          { tone: "unavailable", value: o.not_available },
          { tone: "failed", value: failed },
        ]}
        text={T.dc.barText.orders(n(o.stored), n(o.referenced), n(o.waiting), n(o.not_available), n(failed))}
        showText={false}
      />
      <ProgressLegend
        items={[
          { tone: "done", label: T.dc.legend.done! },
          { tone: "waiting", label: T.dc.legend.waiting! },
          { tone: "unavailable", label: T.dc.legend.unavailable! },
          { tone: "failed", label: T.dc.legend.failed! },
        ]}
      />
      <p className={ds.line}>{T.dc.ordersLine(n(o.waiting), n(o.not_available))}</p>
    </Tile>
  );
}

function LeftTile({ data }: { data: DataOverview }) {
  const left = data.left;
  return (
    <Tile index={3} title={T.dc.leftTitle} tooltip={T.dc.leftTooltip} big={<Count value={left.total} />}>
      <p className={ds.line}>{T.dc.leftLine(n(left.causelist_days), n(left.case_details), n(left.order_pdfs))}</p>
      <Collapsible summary={T.dc.waitingWorkTitle}>
        <DataTable
          caption={T.dc.waitingWorkTitle}
          rows={data.waiting_work}
          rowKey={(r) => r.kind}
          empty={<p className={ds.line}>{T.dc.nothingLeft}</p>}
          columns={[
            { key: "kind", header: T.dc.cols.kind, primary: true, cell: (r) => T.dc.kinds[r.kind] ?? r.kind },
            { key: "total", header: T.dc.cols.total, align: "right", cell: (r) => n(r.total) },
            ...LANES.map((lane) => ({
              key: lane,
              header: T.dc.lanes[lane]!,
              align: "right" as const,
              cell: (r: DataOverview["waiting_work"][number]) => n(r.by_lane[lane]),
            })),
            { key: "running", header: T.dc.cols.fetching, align: "right", cell: (r) => n(r.running) },
            { key: "failed", header: T.dc.cols.failed, align: "right", cell: (r) => n(r.failed) },
          ]}
        />
      </Collapsible>
    </Tile>
  );
}

function ProblemsLine({ problems }: { problems: DataOverview["problems"] }) {
  const parts = problemParts(problems);
  return (
    <p className={ds.problems} aria-label={T.dc.problemsLabel}>
      <b>{T.dc.problemsLabel}:</b>
      {parts.length === 0 ? (
        <Badge tone="success">{T.dc.noProblems}</Badge>
      ) : (
        parts.map((p, i) => {
          const href = PROBLEM_LINKS[p.key];
          return (
            <span key={p.key}>
              {i > 0 ? <span className={ds.sep}> · </span> : null}
              {href ? <Link href={href}>{p.text}</Link> : <span>{p.text}</span>}
            </span>
          );
        })
      )}
    </p>
  );
}

function RightNow({
  pulse,
  fetchedAt,
  error,
  showCollect,
}: {
  pulse: DataPulse | undefined;
  fetchedAt: number;
  error: unknown;
  showCollect: boolean;
}) {
  const since = useSecondsSince(fetchedAt || null);
  const now = fetchedAt + (since ?? 0) * 1000;
  const fetching = new Map<string, number>();
  for (const r of pulse?.running ?? []) fetching.set(r.kind, (fetching.get(r.kind) ?? 0) + 1);
  const w = pulse?.window;
  const minutes = w ? minutesToReset(w.seconds_to_next_reset, fetchedAt, now) : null;
  return (
    <section className={ds.panel} aria-labelledby="dc-right-now">
      <div className="stack">
        <h2 id="dc-right-now">{T.dc.rightNowTitle}</h2>
        <ErrorBanner error={error} />
        {pulse ? (
          <div className={ds.rightNow}>
            <div>
              <h3>{T.dc.fetchingNow}</h3>
              {fetching.size === 0 ? (
                <p className={ds.line}>{T.dc.nothingFetchingNote}</p>
              ) : (
                <ul className={ds.chips}>
                  {[...fetching.entries()].map(([kind, count]) => (
                    <li key={kind} className={ds.pulse}>
                      <Badge tone="info">{`${T.dc.kinds[kind] ?? kind} · ${n(count)}`}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3>{T.dc.callsThisHour}</h3>
              <ProgressBar
                label={T.dc.callsThisHour}
                size="sm"
                max={w?.hourly_limit ?? Math.max(w?.used ?? 0, 1)}
                segments={[{ tone: "active", value: w?.used ?? 0 }]}
                text={w?.hourly_limit ? T.dc.callsBar(n(w.used), n(w.hourly_limit)) : T.dc.callsBarNoLimit(n(w?.used))}
              />
              <p className={ds.line} aria-live="off">
                {minutes === null ? T.dc.resetUnknownNote : T.dc.nextResetIn(minutes)}
              </p>
            </div>
            <div>
              <h3>{T.dc.requestsInProgress}</h3>
              <p className={ds.big}>
                <Count value={pulse.requests_active} />
              </p>
              {showCollect ? <Link href="/data/collect">{T.dc.openCollectNow}</Link> : null}
            </div>
          </div>
        ) : error ? null : (
          <Loading />
        )}
      </div>
    </section>
  );
}

function EstimateCard({ data }: { data: DataOverview }) {
  const e = data.estimate;
  const limit = e.basis.hourly_limit;
  return (
    <section className={ds.panel} aria-labelledby="dc-estimate">
      <div className="stack">
        <h2 id="dc-estimate">{T.dc.estimateTitle}</h2>
        <p>{estimateText(e.details, "details")}</p>
        <p>{estimateText(e.all, "all")}</p>
        <p className={ds.line}>{T.dc.basisLine(n(Math.round(e.basis.calls_per_hour)), limit ? n(limit) : null)}</p>
        <Collapsible summary={T.dc.howTitle}>
          <ul>
            {estimateInputs(e).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Collapsible>
      </div>
    </section>
  );
}

type MonthTableRow = { kind: "month"; m: MonthRow } | { kind: "earlier"; first: string; o: NonNullable<Coverage["earlier_orders"]> };

function MonthsCard({
  data,
  pending,
  error,
  refetch,
  readsDays,
}: {
  data: Coverage | undefined;
  pending: boolean;
  error: unknown;
  refetch: () => void;
  readsDays: boolean;
}) {
  const [month, setMonth] = useState<string | null>(null);
  const rows: MonthTableRow[] = (data?.months ?? []).map((m) => ({ kind: "month", m }));
  if (data?.earlier_orders && data.months.length > 0) {
    rows.push({ kind: "earlier", first: data.months[0]!.month, o: data.earlier_orders });
  }
  const muted = (r: MonthTableRow) => r.kind === "month" && r.m.state === "not_reached";
  return (
    <section className={ds.panel} aria-labelledby="dc-months">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="dc-months">{T.dc.monthsTitle}</h2>
          <Button variant="secondary" onClick={refetch}>
            {T.dc.refresh}
          </Button>
        </div>
        <p className={ds.line}>{T.dc.monthsNote}</p>
        <ErrorBanner error={error} onRetry={refetch} />
        {pending ? <Loading lines={4} /> : null}
        {data && data.months.length === 0 ? <EmptyState>{T.dc.noMonthsNote}</EmptyState> : null}
        {data && data.months.length > 0 ? (
          <ScrollBox label={T.dc.monthsTitle}>
            <DataTable
              caption={T.dc.monthsTitle}
              rows={rows}
              rowKey={(r) => (r.kind === "month" ? r.m.month : "earlier")}
              rowClassName={(r) => (muted(r) ? ds.muted : undefined)}
              columns={[
                {
                  key: "month",
                  header: T.dc.cols.month,
                  primary: true,
                  cell: (r) => (r.kind === "month" ? monthName(r.m.month) : T.dc.earlierRow(monthName(r.first))),
                },
                {
                  key: "lists",
                  header: T.dc.cols.causeLists,
                  cell: (r) => (r.kind === "month" ? <DaysCell m={r.m} /> : "—"),
                },
                {
                  key: "entries",
                  header: T.dc.cols.listsEntries,
                  cell: (r) => (r.kind === "month" ? T.dc.listsEntries(n(r.m.lists), n(r.m.entries)) : "—"),
                },
                {
                  key: "cases",
                  header: T.dc.cols.caseDetails,
                  cell: (r) =>
                    r.kind === "month" ? (
                      <span className={ds.cellBar}>
                        <ProgressBar
                          size="sm"
                          label={T.dc.cols.caseDetails}
                          max={r.m.cases.listed}
                          segments={[{ tone: "done", value: r.m.cases.with_details }]}
                          text={T.dc.casesOf(n(r.m.cases.with_details), n(r.m.cases.listed))}
                        />
                      </span>
                    ) : (
                      "—"
                    ),
                },
                {
                  key: "orders",
                  header: T.dc.cols.orderPdfs,
                  cell: (r) => {
                    const o = r.kind === "month" ? r.m.orders : r.o;
                    return (
                      <span className={ds.cellBar}>
                        <ProgressBar
                          size="sm"
                          label={T.dc.cols.orderPdfs}
                          max={o.referenced}
                          segments={[
                            { tone: "done", value: o.stored },
                            { tone: "waiting", value: o.waiting },
                            { tone: "unavailable", value: o.not_available },
                            { tone: "failed", value: o.failed ?? 0 },
                          ]}
                          text={T.dc.ordersOf(n(o.stored), n(o.referenced), n(o.waiting))}
                        />
                      </span>
                    );
                  },
                },
                {
                  key: "left",
                  header: T.dc.cols.stillToFetch,
                  cell: (r) => (r.kind === "month" ? monthLeft(r.m) : r.o.waiting > 0 ? T.dc.leftParts.order_pdfs!(n(r.o.waiting)) : T.dc.nothingLeft),
                },
                {
                  key: "problems",
                  header: T.dc.cols.problems,
                  cell: (r) => {
                    const parts = r.kind === "month" ? monthProblems(r.m) : [];
                    if (parts.length === 0) return "—";
                    return <Link href={PROBLEM_LINKS.failed!}>{parts.join(" · ")}</Link>;
                  },
                },
                ...(readsDays
                  ? [
                      {
                        key: "days",
                        header: <span className="visually-hidden">{T.dc.cols.days}</span>,
                        label: T.dc.cols.days,
                        cell: (r: MonthTableRow) =>
                          r.kind === "month" ? (
                            <Button
                              variant="link"
                              onClick={() => setMonth(r.m.month)}
                              aria-label={T.dc.daysFor(monthName(r.m.month))}
                            >
                              {T.dc.daysButton}
                            </Button>
                          ) : null,
                      },
                    ]
                  : []),
              ]}
            />
          </ScrollBox>
        ) : null}
      </div>
      {month ? <DaysDialog month={month} onClose={() => setMonth(null)} /> : null}
    </section>
  );
}

function DaysCell({ m }: { m: MonthRow }) {
  const done = m.days.with_lists + m.days.no_list;
  const state = m.state ?? "not_in_load";
  return (
    <span className={ds.cellBar}>
      <ProgressBar
        size="sm"
        label={T.dc.cols.causeLists}
        max={m.days.calendar}
        segments={[
          { tone: "done", value: done },
          { tone: "waiting", value: m.days.waiting },
          { tone: "failed", value: m.days.failed },
        ]}
        text={T.dc.daysOf(n(done), n(m.days.calendar))}
      />
      <span>
        <Badge tone={monthTone(state)}>{T.dc.monthStates[state] ?? state}</Badge>
      </span>
    </span>
  );
}

function DaysDialog({ month, onClose }: { month: string; onClose: () => void }) {
  const days = useQuery({
    queryKey: ["data-load", "days", month],
    queryFn: () => api<QueueList>("/admin/napix/queue", { query: { kind: "causelist_day", ref: month, limit: 31 } }),
  });
  return (
    <Dialog open title={T.dc.daysFor(monthName(month))} onClose={onClose}>
      {days.isPending ? <Loading /> : null}
      <ErrorBanner error={days.error} onRetry={() => days.refetch()} />
      {days.data ? (
        <ScrollBox label={T.dc.daysFor(monthName(month))}>
          <DataTable
            caption={T.dc.daysFor(monthName(month))}
            rows={days.data.items}
            rowKey={(r) => r.id}
            empty={<EmptyState>{T.dc.daysDialogEmpty}</EmptyState>}
            columns={[
              { key: "date", header: T.dc.cols.date, primary: true, cell: (r) => formatDate(r.ref) },
              { key: "status", header: T.dc.cols.status, cell: (r) => T.dc.dayStates[r.status] ?? r.status },
              { key: "lane", header: T.dc.cols.kindOfWork, cell: (r) => T.dc.lanes[r.lane] ?? r.lane },
              { key: "attempts", header: T.dc.cols.attempts, align: "right", cell: (r) => r.attempts },
            ]}
          />
        </ScrollBox>
      ) : null}
    </Dialog>
  );
}
