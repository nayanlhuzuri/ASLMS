"use client";

/**
 * The Research Index section of Data Collection → Overview (design research-index-portal, decisions 18 and 19), for the
 * readers of data health only (`HEALTH_READERS`, the guard of `GET /admin/data-health`). It reads the snapshot's
 * `research_index` block with the query key `["data-health"]` that Problems and Fixes' Recorded Problems uses, so the two
 * share one cached copy; every 120 s while the tab is visible and on Refresh. Statistics only: there is no button that
 * starts, retries or rebuilds indexing (the CLI `aslms research-index` does, runbook section 28).
 *
 * The status line (Meaning Search On or Off, the Model badge from `readiness`, the live model key in mono), the
 * coverage bar (success from 99%, the server's `ready` threshold), the chunk counts, the chunks not embedded with the
 * link to Recorded Problems, earlier models' vectors, the last run and the last full check, and the table sizes. A
 * count that took too long shows "Not Known Right Now", never 0, with the muted line to press Refresh.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge, Button, DataTable, ErrorBanner, KvList, Loading, ProgressBar, type Tone } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DataHealth, ResearchIndexStatus } from "@/lib/api/types";
import { canAny } from "@/lib/can";
import { POLL } from "@/lib/dataCollection";
import { labelFor } from "@/lib/displayLabels";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { HEALTH_READERS } from "@/lib/routes";

import ds from "./data.module.css";

const R = T.dc.research;
export const HEALTH_KEY = ["data-health"] as const;
/** The server's `ready` threshold: the bar turns success from here. */
export const READY_COVERAGE = 0.99;
const TABLES = ["research_chunks", "research_embeddings"] as const;

/** `research_index: null` (the block failed on the server): said in words, with Try Again. */
const UNREAD = { code: "research_unread" };
const UNREAD_TEXT = { research_unread: () => R.unread };

const READINESS_TONE: Record<string, Tone | undefined> = { ready: "success", held: "info", unavailable: "warning", off: undefined };

function pct(coverage: number): string {
  const whole = Math.floor(coverage * 100);
  return coverage > 0 && whole < 1 ? T.assistant.research.underOne : `${whole}%`;
}

function RunLine({ run }: { run: ResearchIndexStatus["last_run"] }) {
  if (!run) return <>{R.notYet}</>;
  const c = (run.counters ?? {}) as Record<string, unknown>;
  const counts =
    typeof c.embedded === "number" || typeof c.cut === "number"
      ? ` · ${R.runCounts(formatNumber(Number(c.embedded ?? 0)), formatNumber(Number(c.cut ?? 0)))}`
      : "";
  return (
    <>
      {formatDateTime(run.finished_at ?? run.started_at)} · {labelFor(T.dc.results, run.status)}
      {counts}
    </>
  );
}

function CheckLine({ run }: { run: ResearchIndexStatus["last_reconcile"] }) {
  if (!run) return <>{R.notYet}</>;
  return (
    <>
      {formatDateTime(run.finished_at ?? run.started_at)} · {labelFor(T.dc.results, run.status)}
    </>
  );
}

/** The block itself (decision 19), drawn from `research_index` alone. */
export function ResearchIndexBody({ r }: { r: ResearchIndexStatus }) {
  const timed = new Set(r.timed_out ?? []);
  const countsLate = timed.has("counts");
  const sizesLate = timed.has("sizes");
  const chunks = r.chunks ?? null;
  const known = (v: number | null | undefined) => (countsLate || v === null || v === undefined ? R.notKnownNow : formatNumber(v));
  const status = (
    <div className={ds.researchStatus}>
      <span>
        {R.meaningSearch} <Badge tone={r.enabled ? "success" : undefined}>{r.enabled ? R.on : R.off}</Badge>
      </span>
      <span>
        {R.model} <Badge tone={READINESS_TONE[r.readiness]}>{labelFor(R.readiness, r.readiness)}</Badge>
        {r.readiness === "held" ? <span className={ds.line}> {R.heldNote}</span> : null}
      </span>
      <span className={ds.researchKey}>
        {R.liveModel} {r.live_model_key ? <code className="mono">{r.live_model_key}</code> : <span>{R.notKnown}</span>}
      </span>
    </div>
  );
  const chunkList = (
    <KvList
      items={[
        [R.orderPassages, known(chunks?.order_body)],
        [R.caseSheets, known(chunks?.case_sheet)],
        [R.waiting, known(r.waiting)],
      ]}
    />
  );
  if (!r.enabled) {
    return (
      <div className="stack">
        {status}
        <p className={ds.line}>{R.switchedOff}</p>
        {chunkList}
        {countsLate ? <p className={ds.line}>{R.timedOut}</p> : null}
      </div>
    );
  }
  const total = chunks?.total ?? 0;
  const live = r.vectors_live ?? 0;
  const coverage = r.coverage ?? (total > 0 ? live / total : 0);
  const ready = coverage >= READY_COVERAGE;
  const others = Object.entries(r.other_keys ?? {});
  const sizes = r.table_sizes ?? {};
  return (
    <div className="stack">
      {status}
      <div>
        <h3>{R.coverage}</h3>
        {countsLate || !chunks ? (
          <p data-ui="research-coverage-unknown">{R.notKnownNow}</p>
        ) : (
          <ProgressBar
            label={R.coverage}
            max={Math.max(total, 1)}
            segments={[
              { tone: ready ? "done" : "active", value: live },
              { tone: "waiting", value: Math.max(0, r.waiting ?? total - live) },
            ]}
            text={R.coverageText(pct(coverage), formatNumber(r.waiting ?? Math.max(0, total - live)))}
          />
        )}
      </div>
      <div>
        <h3>{R.chunks}</h3>
        {chunkList}
        <p className={ds.line}>
          {r.failures_open > 0 ? <Link href="/data/problems#failed">{R.notEmbedded(r.failures_open)}</Link> : R.noneFailed}
        </p>
      </div>
      {countsLate ? <p className={ds.line}>{R.timedOut}</p> : null}
      {others.length > 0 && !countsLate ? (
        <div>
          <h3>{R.earlierTitle}</h3>
          <p className={ds.line}>{R.earlierLine}</p>
          <DataTable
            caption={R.earlierTitle}
            rows={others}
            rowKey={([key]) => key}
            columns={[
              { key: "key", header: R.earlierCols.key, primary: true, cell: ([key]) => <code className="mono">{key}</code> },
              { key: "vectors", header: R.earlierCols.vectors, align: "right", cell: ([, n]) => formatNumber(n) },
            ]}
          />
        </div>
      ) : null}
      <div>
        <h3>{R.runs}</h3>
        <KvList
          items={[
            [R.lastRun, <RunLine key="run" run={r.last_run} />],
            [R.lastCheck, <CheckLine key="check" run={r.last_reconcile} />],
          ]}
        />
      </div>
      <div>
        <h3>{R.space}</h3>
        <KvList
          items={TABLES.map((table) => [
            labelFor(R.tables, table),
            sizesLate || sizes[table] === undefined ? R.notKnownNow : formatBytes(sizes[table]),
          ])}
        />
        {sizesLate ? <p className={ds.line}>{R.timedOut}</p> : null}
      </div>
    </div>
  );
}

/** The section on the Overview (decision 18): hidden without a health-reader function. */
export function ResearchIndexSection() {
  const me = useMe();
  const reader = canAny(me.data, HEALTH_READERS);
  const health = useQuery({
    queryKey: HEALTH_KEY,
    queryFn: () => api<DataHealth>("/admin/data-health"),
    enabled: reader,
    refetchInterval: POLL.months,
    refetchIntervalInBackground: false,
  });
  if (!reader) return null;
  const block = health.data?.research_index ?? null;
  return (
    <section className={ds.panel} id="research-index" aria-labelledby="dc-research-index">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="dc-research-index">{R.title}</h2>
          <Button variant="secondary" onClick={() => void health.refetch()}>
            {T.dc.refresh}
          </Button>
        </div>
        {health.isPending ? <Loading lines={4} /> : null}
        {health.error ? <ErrorBanner error={health.error} onRetry={() => void health.refetch()} /> : null}
        {health.data && !block ? (
          <ErrorBanner error={UNREAD} messages={UNREAD_TEXT} onRetry={() => void health.refetch()} />
        ) : null}
        {block ? <ResearchIndexBody r={block} /> : null}
      </div>
    </section>
  );
}
