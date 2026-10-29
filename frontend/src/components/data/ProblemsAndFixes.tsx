"use client";

/**
 * Problems and Fixes (design data-collection-redesign, decisions 42-46): the Court Connection line with Check the
 * Court Connection, Failed Fetches (a summary by kind with Retry All, the failed items with Retry), Possible Duplicates
 * (three kinds, Scan Now) and Data Gaps (cases without details with Collect These, orders not available or failed with
 * Try Again, documents without searchable text). Each section heading carries its count and each section has an empty
 * state. Every figure is shown to every reader; each button only to the holder of its function, and every action is an
 * existing endpoint with its own audit. The page has no primary.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useId, useState, type ReactNode } from "react";

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  Pagination,
  ScrollBox,
  SegmentedSwitch,
  TabToolbar,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type {
  DataHealth,
  DedupeScan,
  DuplicateItem,
  Duplicates as DuplicatesList,
  FetchDetails,
  HealthCheck,
  NapixHealth,
  QueueList,
  QueueState,
  RetryFailed,
} from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import {
  DC_KEYS,
  failedWhat,
  POLL,
  familyWords,
  retryFunction,
  type DataGaps,
  type DataOverview,
  type DataPulse,
  type GapCase,
  type GapOrder,
} from "@/lib/dataCollection";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { HEALTH_READERS } from "@/lib/routes";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";
import { useOverview } from "./Overview";

const LIMIT = 50;
const n = (v: number | null | undefined) => formatNumber(v ?? 0);
const NAPIX_KEY = ["data-health", "napix"] as const;

/** Scrolls to the address's anchor (`#failed`, `#duplicates`, `#gaps`) once the sections are drawn. */
function useAnchor(ready: boolean) {
  useEffect(() => {
    if (!ready || typeof window === "undefined" || !window.location.hash) return;
    const el = document.getElementById(window.location.hash.slice(1));
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "start" });
  }, [ready]);
}

export function ProblemsAndFixes() {
  const me = useMe();
  const overview = useOverview();
  const healthReader = canAny(me.data, HEALTH_READERS);
  const data = overview.data;
  useAnchor(!!data);
  const acts = can(me.data, "admin.data_load") || canAny(me.data, ["admin.napix_refetch", "admin.masters_sync"]);
  return (
    <div className="stack">
      <TabToolbar updatedAt={overview.dataUpdatedAt || null} />
      <ErrorBanner error={overview.error} onRetry={() => overview.refetch()} />
      {!acts ? <p className={ds.line}>{T.pf.readOnlyNote}</p> : null}
      <CourtConnection healthReader={healthReader} />
      {overview.isPending ? <Loading lines={6} /> : null}
      {data ? (
        <>
          <FailedFetches data={data} healthReader={healthReader} />
          <PossibleDuplicates review={data.problems.duplicates_review} />
          <DataGapsSection data={data} />
        </>
      ) : null}
    </div>
  );
}

/** One section of the tab: its anchor, and a heading that carries its count (decision 42). */
function Section({ id, title, count, children }: { id: string; title: string; count: number; children: ReactNode }) {
  return (
    <section className={ds.panel} id={id} aria-labelledby={`${id}-heading`}>
      <div className="stack">
        <h2 id={`${id}-heading`}>{T.pf.withCount(title, n(count))}</h2>
        {children}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ court connection

/** The Court Connection line (decision 43) and whether it reports a failure. */
function connectionLine(napix: NapixHealth | undefined, lastCall: string | null | undefined): { text: string; failed: boolean } {
  if (napix) {
    if (!napix.enabled) return { text: T.pf.connectionOff, failed: false };
    const failure = napix.last_failure;
    const okAt = napix.last_ok_at ? new Date(napix.last_ok_at).getTime() : 0;
    if (failure && new Date(failure.called_at).getTime() > okAt) {
      return { text: T.pf.failedAt(formatDateTime(failure.called_at), familyWords(failure.error_family)), failed: true };
    }
    if (napix.last_ok_at) return { text: T.pf.answeredAt(formatDateTime(napix.last_ok_at)), failed: false };
    return { text: T.pf.noCallYet, failed: false };
  }
  return { text: lastCall ? T.pf.lastCallAt(formatDateTime(lastCall)) : T.pf.noCallYet, failed: false };
}

function CourtConnection({ healthReader }: { healthReader: boolean }) {
  const me = useMe();
  const qc = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  // the court-health block for its readers; the pulse's last call for the other readers (admin.data_load alone)
  const napix = useQuery({
    queryKey: NAPIX_KEY,
    queryFn: () => api<NapixHealth>("/admin/napix/health"),
    enabled: healthReader,
  });
  const pulse = useQuery({
    queryKey: DC_KEYS.pulse,
    queryFn: () => api<DataPulse>("/admin/data-load/pulse"),
    enabled: !healthReader,
    refetchInterval: POLL.overview,
    refetchIntervalInBackground: false,
  });
  const checker = canAny(me.data, ["admin.napix_refetch", "admin.masters_sync"]);
  async function check() {
    setMessage(null);
    const out = await action.run(() => api<HealthCheck>("/admin/napix/health/check", { method: "POST" }));
    if (out.ok) {
      setMessage(out.value.ok ? T.pf.checkOk : T.pf.checkFailed(familyWords(out.value.error_family)));
      await qc.invalidateQueries({ queryKey: NAPIX_KEY });
    }
  }
  const line = connectionLine(napix.data, pulse.data?.last_call_at);
  return (
    <section className={ds.panel} id="connection" aria-labelledby="connection-heading">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="connection-heading">{T.pf.connectionTitle}</h2>
          {checker ? (
            <Button variant="secondary" busy={action.busy} onClick={check}>
              {T.pf.checkButton}
            </Button>
          ) : null}
        </div>
        <ErrorBanner error={action.error ?? napix.error} />
        {healthReader && napix.isPending ? (
          <Loading lines={1} />
        ) : (
          <p className={ds.line}>
            {line.failed ? <Badge tone="danger">{T.dc.legend.failed}</Badge> : null} {line.text}
          </p>
        )}
        {napix.data?.last_check ? (
          <p className={ds.line}>
            {T.pf.lastCheck(
              formatDateTime(napix.data.last_check.called_at),
              napix.data.last_check.ok,
              familyWords(napix.data.last_check.error_family),
            )}
          </p>
        ) : null}
        {message ? <Notice>{message}</Notice> : null}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ failed fetches

function FailedFetches({ data, healthReader }: { data: DataOverview; healthReader: boolean }) {
  const me = useMe();
  const qc = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const total = data.problems.failed;
  const byKind = data.waiting_work.filter((r) => r.failed > 0);
  const rows = useQuery({
    queryKey: [...DC_KEYS.failed, offset],
    queryFn: () => api<QueueList>("/admin/napix/queue", { query: { status: "failed", limit: LIMIT, offset } }),
    enabled: healthReader && total > 0,
  });
  async function refresh() {
    await Promise.all([qc.invalidateQueries({ queryKey: DC_KEYS.failed }), qc.invalidateQueries({ queryKey: DC_KEYS.overview })]);
  }
  async function retryAll(kind: string) {
    setMessage(null);
    const out = await action.run(() => api<RetryFailed>("/admin/napix/queue/retry-failed", { method: "POST", body: { kind } }));
    if (out.ok) {
      setMessage(T.pf.retriedNote(out.value.retried, T.dc.kinds[kind] ?? kind));
      await refresh();
    }
  }
  async function retry(id: string) {
    setMessage(null);
    const out = await action.run(() => api<QueueState>(`/admin/napix/queue/${id}/retry`, { method: "POST" }));
    if (out.ok) {
      setMessage(T.pf.retriedOne);
      await refresh();
    }
  }
  return (
    <Section id="failed" title={T.pf.failedTitle} count={total}>
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      {total === 0 ? (
        <EmptyState>{T.pf.failedNone}</EmptyState>
      ) : (
        <>
          <h3>{T.pf.failedByKind}</h3>
          <DataTable
            caption={T.pf.failedByKind}
            rows={byKind}
            rowKey={(r) => r.kind}
            columns={[
              { key: "kind", header: T.pf.cols.kindOfWork, primary: true, cell: (r) => T.dc.kinds[r.kind] ?? r.kind },
              { key: "failed", header: T.dc.cols.failed, align: "right", cell: (r) => n(r.failed) },
              {
                key: "retry",
                header: <span className="visually-hidden">{T.pf.retryAll}</span>,
                label: T.pf.retryAll,
                cell: (r) =>
                  can(me.data, retryFunction(r.kind)) ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      busy={action.busy}
                      onClick={() => retryAll(r.kind)}
                      aria-label={T.pf.retryAllOf(T.dc.kinds[r.kind] ?? r.kind)}
                    >
                      {T.pf.retryAll}
                    </Button>
                  ) : null,
              },
            ]}
          />
          {healthReader ? (
            <>
              <ErrorBanner error={rows.error} onRetry={() => rows.refetch()} />
              {rows.isPending ? <Loading /> : null}
              {rows.data ? (
                <>
                  <ScrollBox label={T.pf.failedTitle}>
                    <DataTable
                      caption={T.pf.failedTitle}
                      rows={rows.data.items}
                      rowKey={(r) => r.id}
                      empty={<EmptyState>{T.pf.failedNone}</EmptyState>}
                      columns={[
                        { key: "when", header: T.pf.cols.when, cell: (r) => formatDateTime(r.finished_at ?? r.updated_at) },
                        { key: "what", header: T.pf.cols.what, primary: true, cell: (r) => <span title={r.ref}>{failedWhat(r.kind, r.ref)}</span> },
                        { key: "kind", header: T.pf.cols.kindOfWork, cell: (r) => T.dc.kinds[r.kind] ?? r.kind },
                        { key: "tries", header: T.pf.cols.tries, align: "right", cell: (r) => r.attempts },
                        { key: "problem", header: T.pf.cols.problem, cell: (r) => r.last_error ?? "—" },
                        {
                          key: "retry",
                          header: <span className="visually-hidden">{T.pf.retry}</span>,
                          label: T.pf.retry,
                          cell: (r) =>
                            can(me.data, retryFunction(r.kind)) ? (
                              <Button variant="link" busy={action.busy} onClick={() => retry(r.id)}>
                                {T.pf.retry}
                              </Button>
                            ) : null,
                        },
                      ]}
                    />
                  </ScrollBox>
                  <Pagination offset={offset} limit={LIMIT} total={rows.data.total} onChange={setOffset} />
                </>
              ) : null}
            </>
          ) : (
            <p className={ds.line}>{T.pf.failedRowsNote}</p>
          )}
        </>
      )}
      {healthReader ? <RecordedProblems /> : null}
    </Section>
  );
}

/** Words for a recorded problem's kind: its plain name, else the kind's own words. */
function recordedKind(kind: string): string {
  return T.pf.recordedKinds[kind] ?? kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** The open source failures by kind (counts only), as the Health tab listed them (decision 3). */
function RecordedProblems() {
  const snapshot = useQuery({ queryKey: ["data-health"], queryFn: () => api<DataHealth>("/admin/data-health") });
  const rows = snapshot.data?.failures ?? [];
  if (snapshot.error) return <ErrorBanner error={snapshot.error} onRetry={() => snapshot.refetch()} />;
  if (rows.length === 0) return null;
  return (
    <div className="stack">
      <h3>{T.pf.recordedTitle}</h3>
      <p className={ds.line}>{T.pf.recordedNote}</p>
      <DataTable
        caption={T.pf.recordedTitle}
        rows={rows}
        rowKey={(r) => r.kind}
        columns={[
          { key: "kind", header: T.pf.recordedCols.kind, primary: true, cell: (r) => <span title={r.kind}>{recordedKind(r.kind)}</span> },
          { key: "open", header: T.pf.recordedCols.open, align: "right", cell: (r) => n(r.open) },
          { key: "since", header: T.pf.recordedCols.since, cell: (r) => formatDate(r.oldest_first_seen) },
        ]}
      />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ duplicates

const DUP_KINDS = ["review", "merged", "court"] as const;
type DupKind = (typeof DUP_KINDS)[number];

function brief(c: DuplicateItem["case"] | GapCase["case"] | null | undefined) {
  if (!c) return "—";
  return (
    <>
      <Link href={casePath(c.ref_no)} className="mono">
        {c.ref_no}
      </Link>
      <br />
      <span className="mono muted">{[c.cnr, c.case_no_text].filter(Boolean).join(" · ") || "—"}</span>
    </>
  );
}

function PossibleDuplicates({ review }: { review: number }) {
  const me = useMe();
  const qc = useQueryClient();
  const action = useAction();
  const explainId = useId();
  const [kind, setKind] = useState<DupKind>("review");
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const list = useQuery({
    queryKey: [...DC_KEYS.duplicates, kind, offset],
    queryFn: () => api<DuplicatesList>("/admin/data-load/duplicates", { query: { kind, limit: LIMIT, offset } }),
  });
  async function scan() {
    setMessage(null);
    const out = await action.run(() => api<DedupeScan>("/admin/data-load/duplicates/scan", { method: "POST" }));
    if (out.ok) {
      setMessage(T.pf.scanned(out.value.merged, out.value.needs_review, out.value.court_linked));
      await Promise.all([qc.invalidateQueries({ queryKey: DC_KEYS.duplicates }), qc.invalidateQueries({ queryKey: DC_KEYS.overview })]);
    }
  }
  return (
    <Section id="duplicates" title={T.pf.duplicatesTitle} count={review}>
      <div className={ds.panelHead}>
        <SegmentedSwitch
          label={T.pf.duplicateKinds}
          value={kind}
          describedBy={explainId}
          onChange={(v) => {
            setKind(v as DupKind);
            setOffset(0);
          }}
          options={DUP_KINDS.map((k) => ({ value: k, label: T.pf.dupKinds[k]! }))}
        />
        {can(me.data, "admin.data_load") ? (
          <span className={ds.scan}>
            <Button variant="secondary" busy={action.busy} onClick={scan}>
              {T.pf.scanNow}
            </Button>
            <span className={ds.line}>{T.pf.scanHint}</span>
          </span>
        ) : null}
      </div>
      <p className={ds.line} id={explainId}>
        {T.pf.dupExplain[kind]}
      </p>
      <ErrorBanner error={action.error ?? list.error} onRetry={() => list.refetch()} />
      {message ? <Notice>{message}</Notice> : null}
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.pf.dupNone[kind]}</EmptyState>
        ) : (
          <>
            <ScrollBox label={T.pf.dupKinds[kind]!}>
              <DataTable
                caption={T.pf.dupKinds[kind]}
                rows={list.data.items}
                rowKey={(d) => `${d.case?.id ?? ""}-${d.other?.id ?? ""}-${d.at}`}
                columns={[
                  { key: "case", header: T.pf.cols.case, primary: true, cell: (d) => brief(d.case) },
                  { key: "other", header: T.pf.cols.otherCase, cell: (d) => brief(d.other) },
                  { key: "at", header: T.pf.cols.when, cell: (d) => formatDateTime(d.at) },
                  { key: "reason", header: T.pf.cols.reason, cell: (d) => d.reasons ?? "—" },
                ]}
              />
            </ScrollBox>
            <Pagination offset={offset} limit={LIMIT} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </Section>
  );
}

// ------------------------------------------------------------------------------------------------ data gaps

const TEXT_KINDS = ["order", "upload", "attachment"] as const;

function useGaps(kind: "cases" | "orders", offset: number) {
  return useQuery({
    queryKey: [...DC_KEYS.gaps, kind, offset],
    queryFn: () => api<DataGaps>("/admin/data-load/gaps", { query: { kind, limit: LIMIT, offset } }),
  });
}

function DataGapsSection({ data }: { data: DataOverview }) {
  const p = data.problems;
  const total = p.cases_without_details + p.orders_not_available + (p.orders_failed ?? 0);
  const [casesOffset, setCasesOffset] = useState(0);
  const [ordersOffset, setOrdersOffset] = useState(0);
  const cases = useGaps("cases", casesOffset);
  const orders = useGaps("orders", ordersOffset);
  const text = cases.data?.documents_text ?? orders.data?.documents_text;
  return (
    <Section id="gaps" title={T.pf.gapsTitle} count={total}>
      {total === 0 ? <EmptyState>{T.pf.gapsNone}</EmptyState> : null}
      <CasesGap query={cases} offset={casesOffset} onPage={setCasesOffset} />
      <OrdersGap query={orders} offset={ordersOffset} onPage={setOrdersOffset} />
      {text ? <DocumentsGap text={text} /> : null}
    </Section>
  );
}

type GapsQuery = ReturnType<typeof useGaps>;

function CasesGap({ query, offset, onPage }: { query: GapsQuery; offset: number; onPage: (o: number) => void }) {
  const me = useMe();
  const qc = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const items = (query.data?.items ?? []) as GapCase[];
  const toCollect = items.filter((i) => i.state !== "being_fetched").map((i) => i.case.ref_no);
  async function collect() {
    setMessage(null);
    const out = await action.run(() =>
      api<FetchDetails>("/admin/data-load/fetch-details", { method: "POST", body: { cases: toCollect, force: false } }),
    );
    if (out.ok) {
      setMessage(T.pf.collectedNote(out.value.items.filter((i) => i.state === "queued").length));
      await Promise.all([qc.invalidateQueries({ queryKey: DC_KEYS.gaps }), qc.invalidateQueries({ queryKey: DC_KEYS.overview })]);
    }
  }
  const counts = query.data?.counts ?? {};
  const total = query.data?.total ?? 0;
  return (
    <div className="stack">
      <div className={ds.panelHead}>
        <h3>{T.pf.withCount(T.pf.casesGapTitle, n(total))}</h3>
        {can(me.data, "admin.data_load") && toCollect.length > 0 ? (
          <Button variant="secondary" busy={action.busy} onClick={collect} title={T.pf.collectTheseHint(toCollect.length)}>
            {T.pf.collectThese}
          </Button>
        ) : null}
      </div>
      <ErrorBanner error={action.error ?? query.error} onRetry={() => query.refetch()} />
      {message ? <Notice>{message}</Notice> : null}
      {query.isPending ? <Loading /> : null}
      {query.data ? (
        total === 0 ? (
          <EmptyState>{T.pf.casesGapNone}</EmptyState>
        ) : (
          <>
            <ul className={ds.chips} aria-label={T.pf.casesGapTitle}>
              {Object.keys(T.pf.caseStates).map((state) => (
                <li key={state}>
                  <Badge tone={state === "failed" ? "danger" : state === "being_fetched" ? "info" : undefined}>
                    {`${T.pf.caseStates[state]} · ${n(counts[state])}`}
                  </Badge>
                </li>
              ))}
            </ul>
            <ScrollBox label={T.pf.casesGapTitle}>
              <DataTable
                caption={T.pf.casesGapTitle}
                rows={items}
                rowKey={(i) => i.case.id}
                columns={[
                  {
                    key: "case",
                    header: T.pf.cols.case,
                    primary: true,
                    cell: (i) => (
                      <>
                        <Link href={casePath(i.case.ref_no)} className="mono">
                          {i.case.ref_no}
                        </Link>
                        {i.case.case_no_text ? (
                          <>
                            <br />
                            <span className="mono muted">{i.case.case_no_text}</span>
                          </>
                        ) : null}
                      </>
                    ),
                  },
                  { key: "cnr", header: T.pf.cols.cnr, cell: (i) => <span className="mono">{i.case.cnr ?? "—"}</span> },
                  { key: "first", header: T.pf.cols.firstSeen, cell: (i) => formatDate(i.first_seen_at) },
                  {
                    key: "state",
                    header: T.pf.cols.state,
                    cell: (i) => (
                      <span title={i.problem ?? undefined}>
                        <Badge tone={i.state === "failed" ? "danger" : i.state === "being_fetched" ? "info" : undefined}>
                          {T.pf.caseStates[i.state] ?? i.state}
                        </Badge>
                        {i.problem ? (
                          <>
                            <br />
                            <span className={ds.line}>{i.problem}</span>
                          </>
                        ) : null}
                      </span>
                    ),
                  },
                ]}
              />
            </ScrollBox>
            <Pagination offset={offset} limit={LIMIT} total={total} onChange={onPage} />
          </>
        )
      ) : null}
    </div>
  );
}

function OrdersGap({ query, offset, onPage }: { query: GapsQuery; offset: number; onPage: (o: number) => void }) {
  const me = useMe();
  const qc = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const items = (query.data?.items ?? []) as GapOrder[];
  const total = query.data?.total ?? 0;
  const fixer = can(me.data, "admin.napix_refetch");
  async function tryAgain(o: GapOrder) {
    setMessage(null);
    const out = await action.run(() =>
      api<QueueState>("/admin/napix/refetch/order", { method: "POST", body: { case: o.case.ref_no, order_id: o.order_id } }),
    );
    if (out.ok) {
      setMessage(T.pf.triedNote);
      await Promise.all([qc.invalidateQueries({ queryKey: DC_KEYS.gaps }), qc.invalidateQueries({ queryKey: DC_KEYS.overview })]);
    }
  }
  return (
    <div className="stack">
      <h3>{T.pf.withCount(T.pf.ordersGapTitle, n(total))}</h3>
      <ErrorBanner error={action.error ?? query.error} onRetry={() => query.refetch()} />
      {message ? <Notice>{message}</Notice> : null}
      {query.isPending ? <Loading /> : null}
      {query.data ? (
        total === 0 ? (
          <EmptyState>{T.pf.ordersGapNone}</EmptyState>
        ) : (
          <>
            <ScrollBox label={T.pf.ordersGapTitle}>
              <DataTable
                caption={T.pf.ordersGapTitle}
                rows={items}
                rowKey={(o) => o.order_id}
                columns={[
                  { key: "case", header: T.pf.cols.case, cell: (o) => brief(o.case) },
                  { key: "order", header: T.pf.cols.order, primary: true, cell: (o) => o.order_no },
                  { key: "date", header: T.pf.cols.date, cell: (o) => formatDate(o.order_date) },
                  {
                    key: "state",
                    header: T.pf.cols.state,
                    cell: (o) => <Badge tone={o.state === "failed" ? "danger" : undefined}>{T.pf.orderStates[o.state] ?? o.state}</Badge>,
                  },
                  { key: "problem", header: T.pf.cols.problem, cell: (o) => o.problem ?? "—" },
                  ...(fixer
                    ? [
                        {
                          key: "again",
                          header: <span className="visually-hidden">{T.pf.tryAgain}</span>,
                          label: T.pf.tryAgain,
                          cell: (o: GapOrder) => (
                            <Button variant="link" busy={action.busy} onClick={() => tryAgain(o)}>
                              {T.pf.tryAgain}
                            </Button>
                          ),
                        },
                      ]
                    : []),
                ]}
              />
            </ScrollBox>
            <Pagination offset={offset} limit={LIMIT} total={total} onChange={onPage} />
          </>
        )
      ) : null}
    </div>
  );
}

function DocumentsGap({ text }: { text: DataGaps["documents_text"] }) {
  const unread = TEXT_KINDS.reduce((sum, k) => {
    const none = text[k].none;
    return sum + text[k].failed + none.scanned_pdf + none.image + none.doc + none.other;
  }, 0);
  return (
    <div className="stack">
      <h3>{T.pf.withCount(T.pf.documentsGapTitle, n(unread))}</h3>
      <p className={ds.line}>{T.data.documentsTextNote}</p>
      {unread === 0 ? <EmptyState>{T.pf.documentsGapNone}</EmptyState> : null}
      <ScrollBox label={T.pf.documentsGapTitle}>
        <DataTable
          caption={T.pf.documentsGapTitle}
          rows={[...TEXT_KINDS]}
          rowKey={(kind) => kind}
          columns={[
            { key: "kind", header: T.data.docKind, primary: true, cell: (kind) => T.data.docKinds[kind] },
            { key: "pending", header: T.data.textPending, align: "right", cell: (kind) => n(text[kind].pending) },
            { key: "extracted", header: T.data.textExtracted, align: "right", cell: (kind) => n(text[kind].extracted) },
            { key: "failed", header: T.data.textFailed, align: "right", cell: (kind) => n(text[kind].failed) },
            { key: "scanned", header: T.data.textScannedPdf, align: "right", cell: (kind) => n(text[kind].none.scanned_pdf) },
            { key: "image", header: T.data.textImage, align: "right", cell: (kind) => n(text[kind].none.image) },
            { key: "doc", header: T.data.textDoc, align: "right", cell: (kind) => n(text[kind].none.doc) },
            { key: "other", header: T.data.textOther, align: "right", cell: (kind) => n(text[kind].none.other) },
          ]}
        />
      </ScrollBox>
    </div>
  );
}
