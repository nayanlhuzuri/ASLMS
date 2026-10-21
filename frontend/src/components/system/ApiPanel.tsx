"use client";

/**
 * One court API's panel on the System health screen (design api-health-checker, decision 15): its status and last
 * call, what the test will use (a case is named only when the server says the caller may see it; a name never), the
 * test area (testing, then the result summarised by the server: never the court's answer itself), the last 7 days as
 * a table (also the screen-reader alternative to the bars), the last 10 calls and the technical details. The panel
 * reads `GET /admin/system-health/napix/{api}` (no court call); "Test now" posts once.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Badge, Button, Collapsible, DataTable, ErrorBanner, KvList, Loading, SidePanel, StatusDot } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { ApiCall, ApiCard, ApiDetail, ApiTest } from "@/lib/api/types";
import { formatDate, formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { errorText, T } from "@/lib/messages";
import { secondsUntil, testBlock, toneOf } from "@/lib/systemHealth";

import s from "./system.module.css";

export interface TestState {
  running: boolean;
  result?: ApiTest;
  error?: unknown;
}

/** "Test now · 1 court call", disabled with the reason as its description; counts down to the next allowed test. */
export function TestButton({
  card,
  napixEnabled,
  running,
  onTest,
}: {
  card: ApiCard;
  napixEnabled: boolean;
  running: boolean;
  onTest: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const waiting = secondsUntil(card.test.next_allowed_at, now) > 0;
  useEffect(() => {
    if (!card.test.next_allowed_at || !waiting) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [card.test.next_allowed_at, waiting]);
  const reason = testBlock(card, napixEnabled, now);
  const id = `test-reason-${card.key}`;
  return (
    <div className={s.testRow}>
      <Button
        variant="secondary"
        disabled={!!reason}
        busy={running}
        aria-describedby={reason ? id : undefined}
        onClick={onTest}
      >
        {T.system.testNow}
      </Button>
      {reason ? (
        <span id={id} className={s.reason}>
          {reason}
        </span>
      ) : null}
    </div>
  );
}

function ResponseBar({ ms, median }: { ms: number; median: number | null | undefined }) {
  const scale = Math.max(ms, median ?? 0, 1) * 1.25;
  return (
    <div className={s.response}>
      <p>
        {T.system.responseTime(formatNumber(ms))}
        {typeof median === "number" ? <span className={s.muted}> · {T.system.median(formatNumber(median))}</span> : null}
      </p>
      <div className={s.track} aria-hidden="true">
        <i className={s.fill} style={{ width: `${((ms / scale) * 100).toFixed(1)}%` }} />
        {typeof median === "number" ? (
          <i className={s.marker} style={{ left: `${((median / scale) * 100).toFixed(1)}%` }} />
        ) : null}
      </div>
    </div>
  );
}

function TestResult({ result, median }: { result: ApiTest; median: number | null | undefined }) {
  const sm = result.summary;
  const items: [string, string][] = [[T.system.reason, result.reason], [T.system.answerKind, T.system.kind[sm.kind] ?? sm.kind]];
  if (sm.row_count !== null && sm.row_count !== undefined) items.push([T.system.rows, formatNumber(sm.row_count)]);
  if (sm.kind !== "pdf") items.push([T.system.fields, sm.field_names.length ? sm.field_names.join(", ") : T.system.none]);
  for (const f of sm.facts) items.push([f.label, f.value]);
  items.push([T.system.attempts, String(result.attempts)]);
  items.push([T.system.callsLeft, result.remaining === null || result.remaining === undefined ? "—" : formatNumber(result.remaining)]);
  return (
    <div className="stack" aria-live="polite">
      <p className={s.resultWord}>
        <Badge tone={toneOf(result.status)}>{T.system.resultWord[result.status] ?? result.status}</Badge>{" "}
        <span className={s.muted}>{formatTime(result.called_at)}</span>
      </p>
      <ResponseBar ms={result.duration_ms} median={median} />
      <KvList items={items} />
    </div>
  );
}

const statuses = (c: ApiCall) => [c.http_status ?? "—", c.napix_status ?? "—"].join(" / ");

export function ApiPanel({
  apiKey,
  card,
  napixEnabled,
  test,
  onTest,
  onClose,
}: {
  apiKey: string | null;
  card: ApiCard | null;
  napixEnabled: boolean;
  test: TestState | undefined;
  onTest: () => void;
  onClose: () => void;
}) {
  const open = !!apiKey && !!card;
  const detail = useQuery({
    queryKey: ["system-health", "api", apiKey, test?.result?.called_at ?? null],
    queryFn: () => api<ApiDetail>(`/admin/system-health/napix/${apiKey}`),
    enabled: open,
  });
  const name = card ? (T.system.apis[card.key] ?? card.label) : "";
  const d = detail.data;
  return (
    <SidePanel open={open} title={name} onClose={onClose}>
      {card ? (
        <div className="stack">
          <p>
            <Badge tone={toneOf(card.status)}>{T.system.status[card.status] ?? card.status_word}</Badge>{" "}
            <span className={s.muted}>
              {card.last_call
                ? T.system.lastCall(formatDateTime(card.last_call.called_at), formatNumber(card.last_call.duration_ms))
                : T.system.noCall}
            </span>
          </p>
          {card.last_test ? (
            <p className={s.muted}>
              {T.system.lastTest(formatDateTime(card.last_test.at), card.last_test.ok, card.last_test.by_you)}
            </p>
          ) : null}
          <ErrorBanner error={detail.error} onRetry={() => void detail.refetch()} />
          {detail.isPending && open ? <Loading lines={2} /> : null}
          {d ? (
            <section className="stack" aria-label={T.system.willUse}>
              <h3>{T.system.willUse}</h3>
              <p>{d.sample.available ? d.sample.label : d.sample.reason}</p>
            </section>
          ) : null}
          <section className="stack" aria-label={T.system.result}>
            <TestButton card={card} napixEnabled={napixEnabled} running={!!test?.running} onTest={onTest} />
            {test?.running ? (
              <p className={s.testing} role="status">
                <StatusDot tone="busy" pulse /> {T.system.testing}
              </p>
            ) : null}
            {test && !test.running && test.error ? <p className={s.error} role="alert">{errorText(test.error)}</p> : null}
            {test && !test.running && test.result ? <TestResult result={test.result} median={card.h24.p50_ms} /> : null}
          </section>
          {d ? (
            <>
              <section className="stack" aria-label={T.system.days}>
                <h3>{T.system.days}</h3>
                <DataTable
                  caption={T.system.days}
                  rows={d.days}
                  rowKey={(r) => r.date}
                  columns={[
                    { key: "date", header: T.system.day, cell: (r) => formatDate(r.date), primary: true },
                    { key: "calls", header: T.system.calls, cell: (r) => formatNumber(r.calls), align: "right" },
                    { key: "answered", header: T.system.answered, cell: (r) => formatNumber(r.answered), align: "right" },
                    { key: "failed", header: T.system.failed, cell: (r) => formatNumber(r.failed), align: "right" },
                    { key: "avg", header: T.system.avgMs, cell: (r) => (r.avg_ms === null ? "—" : formatNumber(r.avg_ms)), align: "right" },
                  ]}
                />
              </section>
              <section className="stack" aria-label={T.system.recent}>
                <h3>{T.system.recent}</h3>
                <DataTable
                  caption={T.system.recent}
                  rows={d.recent}
                  rowKey={(r) => `${r.called_at}-${r.duration_ms}-${r.reason}`}
                  empty={<p className={s.muted}>{T.system.noCall}</p>}
                  columns={[
                    { key: "time", header: T.system.time, cell: (r) => formatDateTime(r.called_at), primary: true },
                    {
                      key: "outcome",
                      header: T.system.outcome,
                      cell: (r) => (r.answered ? T.system.answered : T.system.failed),
                    },
                    { key: "ms", header: T.system.ms, cell: (r) => formatNumber(r.duration_ms), align: "right" },
                    { key: "statuses", header: T.system.statuses, cell: statuses },
                    { key: "reason", header: T.system.reason, cell: (r) => r.reason },
                    { key: "who", header: T.system.who, cell: (r) => T.system.by[r.by] ?? r.by },
                  ]}
                />
              </section>
              <Collapsible summary={T.system.technical}>
                <KvList
                  items={[
                    [T.system.apiName, d.technical.name],
                    [T.system.path, d.technical.path],
                    [T.system.method, d.technical.method],
                    [T.system.inputs, d.technical.input_fields.length ? d.technical.input_fields.join(", ") : T.system.none],
                  ]}
                />
              </Collapsible>
            </>
          ) : null}
        </div>
      ) : null}
    </SidePanel>
  );
}
