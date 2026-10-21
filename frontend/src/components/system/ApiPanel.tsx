"use client";

/**
 * The History tab of a court API's console (design system-health-inspector, decision 1; row 109's panel content
 * unchanged): the status and last call, the last test, what a send would be pre-filled from (a case is named only when
 * the server says the caller may see it), the last 7 days as a table (also the screen-reader alternative to the bars)
 * and the last 10 calls. It reads `GET /admin/system-health/napix/{api}` (no court call).
 */
import { useQuery } from "@tanstack/react-query";

import { Badge, DataTable, ErrorBanner, KvList, Loading } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { ApiCall, ApiCard, ApiDetail } from "@/lib/api/types";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { toneOf } from "@/lib/systemHealth";

import s from "./system.module.css";

const statuses = (c: ApiCall) => [c.http_status ?? "—", c.napix_status ?? "—"].join(" / ");

export function ApiHistory({ apiKey, card, version }: { apiKey: string; card: ApiCard; version?: string | null }) {
  const detail = useQuery({
    queryKey: ["system-health", "api", apiKey, version ?? null],
    queryFn: () => api<ApiDetail>(`/admin/system-health/napix/${apiKey}`),
  });
  const d = detail.data;
  return (
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
        <p className={s.muted}>{T.system.lastTest(formatDateTime(card.last_test.at), card.last_test.ok, card.last_test.by_you)}</p>
      ) : null}
      <ErrorBanner error={detail.error} onRetry={() => void detail.refetch()} />
      {detail.isPending ? <Loading lines={2} /> : null}
      {d ? (
        <>
          <section className="stack" aria-label={T.system.willUse}>
            <h3>{T.system.willUse}</h3>
            <p>{d.sample.available ? d.sample.label : d.sample.reason}</p>
          </section>
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
                { key: "outcome", header: T.system.outcome, cell: (r) => (r.answered ? T.system.answered : T.system.failed) },
                { key: "ms", header: T.system.ms, cell: (r) => formatNumber(r.duration_ms), align: "right" },
                { key: "statuses", header: T.system.statuses, cell: statuses },
                { key: "reason", header: T.system.reason, cell: (r) => r.reason },
                { key: "who", header: T.system.who, cell: (r) => T.system.by[r.by] ?? r.by },
              ]}
            />
          </section>
          <KvList
            items={[
              [T.system.apiName, d.technical.name],
              [T.system.path, d.technical.path],
              [T.system.method, d.technical.method],
              [T.system.inputs, d.technical.input_fields.length ? d.technical.input_fields.join(", ") : T.system.none],
            ]}
          />
        </>
      ) : null}
    </div>
  );
}
