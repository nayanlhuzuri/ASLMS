"use client";

/**
 * The data-health tab (design audit-screens, decisions 5-11; data-load-console, decisions 12 and 19): the snapshot of
 * `GET /admin/data-health` and `GET /admin/napix/health`, refreshed every minute, and the buttons. The court gateway
 * block shows the detected quota window, its recent resets and, for the NAPIX operators only (the API sends `by_user`
 * to them alone), the calls by user (design napix-window). Sync masters needs
 * `admin.masters_sync`; the re-fetch buttons `admin.napix_refetch` and warn before queuing data already held ("Fetch
 * anyway" resends with `force`); the connectivity check either function. No GET calls NAPIX. The document text
 * block (design document-ocr, decision 4) counts documents by text status, the ones not read split into scanned PDFs,
 * images and old Word files.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Badge, Button, Dialog, ErrorBanner, Kpi, Loading, Notice, numCell, Table, TextField } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DataHealth, HealthCheck, NapixHealth, QueueState } from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

export const HEALTH_POLL_MS = 60_000;

export function Health() {
  const me = useMe();
  const snapshot = useQuery({
    queryKey: ["data-health"],
    queryFn: () => api<DataHealth>("/admin/data-health"),
    refetchInterval: HEALTH_POLL_MS,
  });
  const napix = useQuery({
    queryKey: ["data-health", "napix"],
    queryFn: () => api<NapixHealth>("/admin/napix/health"),
    refetchInterval: HEALTH_POLL_MS,
  });
  const syncer = can(me.data, "admin.masters_sync");
  const refetcher = can(me.data, "admin.napix_refetch");
  const checker = canAny(me.data, ["admin.napix_refetch", "admin.masters_sync"]);
  return (
    <section className={ds.board} aria-label={T.data.health}>
      {can(me.data, "reports.state") ? (
        // design portal-reports, decision 10: the dated report of the same figures
        <p className={ds.wide}>
          <Link href="/reports/data-health">{T.reports.periodReport}</Link>
        </p>
      ) : null}
      {snapshot.error || napix.error ? (
        <div className={ds.wide}>
          <ErrorBanner error={snapshot.error ?? napix.error} onRetry={() => (snapshot.refetch(), napix.refetch())} />
        </div>
      ) : null}
      {snapshot.isPending || napix.isPending ? (
        <div className={ds.wide}>
          <Loading lines={6} />
        </div>
      ) : null}
      {napix.data ? <NapixBlock data={napix.data} /> : null}
      {snapshot.data ? <SnapshotBlocks data={snapshot.data} /> : null}
      {syncer || refetcher || checker ? <Buttons syncer={syncer} refetcher={refetcher} checker={checker} /> : null}
    </section>
  );
}

function NapixBlock({ data }: { data: NapixHealth }) {
  const w = data.window;
  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.napix}>
      <h2>{T.data.napix}</h2>
      <p>
        {data.enabled ? <Badge tone="success">{T.data.switchApi(true)}</Badge> : <Badge tone="warning">{T.data.switchApi(false)}</Badge>}{" "}
        <span className="muted">{T.data.switchNote}</span>
      </p>
      <div className={ds.kpis}>
        <Kpi
          label={T.data.window}
          value={w.calls}
          sub={`${formatNumber(w.failed)} ${T.data.failed.toLowerCase()}`}
          tone={w.failed > 0 ? "danger" : undefined}
        />
        <Kpi
          label={T.data.today}
          value={data.today.calls}
          sub={`${formatNumber(data.today.failed)} ${T.data.failed.toLowerCase()}`}
          tone={data.today.failed > 0 ? "danger" : undefined}
        />
      </div>
      <p>{T.data.windowLine(w.status, formatTime(w.started_at), formatTime(w.next_reset_at), Math.round(w.probe_seconds / 60))}</p>
      <p>{w.remaining === null || w.remaining === undefined ? T.data.remainingUnknown : T.data.remaining(formatNumber(w.remaining))}</p>
      <p className="muted">
        {T.data.lastCall}: {formatDateTime(data.last_call_at)}. {T.data.lastCheck}:{" "}
        {data.last_check ? `${formatDateTime(data.last_check.called_at)} (${data.last_check.ok ? T.data.ok : data.last_check.error_family ?? "—"})` : "—"}
      </p>
      {w.recent_resets.length > 0 ? (
        <section className="stack" aria-label={T.data.recentResets}>
          <h3>{T.data.recentResets}</h3>
          <ul>
            {w.recent_resets.map((r) => (
              <li key={r.observed_at}>
                {T.data.resetRow(formatTime(r.observed_at), r.previous_remaining, r.remaining)}
                {r.precise ? (
                  <>
                    {" "}
                    <Badge tone="success">{T.data.precise}</Badge>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data.by_user ? <CallsByUser byUser={data.by_user} /> : null}
    </section>
  );
}

type ByUser = NonNullable<NapixHealth["by_user"]>;

function CallsByUser({ byUser }: { byUser: ByUser }) {
  const ids = Array.from(new Set([...byUser.window, ...byUser.today].map((u) => u.user_id)));
  const names = new Map([...byUser.today, ...byUser.window].map((u) => [u.user_id, u.name]));
  const find = (list: ByUser["window"], id: string) => list.find((u) => u.user_id === id);
  return (
    <section className="stack" aria-label={T.data.byUser}>
      <h3>{T.data.byUser}</h3>
      {ids.length === 0 ? (
        <p className="muted">{T.data.noUserCalls}</p>
      ) : (
        <Table caption={T.data.byUser}>
          <thead>
            <tr>
              <th scope="col">{T.data.user}</th>
              <th scope="col" className={numCell}>{T.data.window}</th>
              <th scope="col" className={numCell}>{T.data.today}</th>
              <th scope="col" className={numCell}>{T.data.failed}</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => (
              <tr key={id}>
                <td>{names.get(id)}</td>
                <td className={numCell}>{formatNumber(find(byUser.window, id)?.calls ?? 0)}</td>
                <td className={numCell}>{formatNumber(find(byUser.today, id)?.calls ?? 0)}</td>
                <td className={numCell}>{formatNumber(find(byUser.today, id)?.failed ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </section>
  );
}

function SnapshotBlocks({ data }: { data: DataHealth }) {
  return (
    <>
      <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.queue}>
        <h2>{T.data.queue}</h2>
        <Table caption={T.data.queue}>
          <thead>
            <tr>
              <th scope="col">{T.data.kind}</th>
              <th scope="col" className={numCell}>{T.data.pending}</th>
              <th scope="col" className={numCell}>{T.data.lanes.load}</th>
              <th scope="col" className={numCell}>{T.data.lanes.discovery}</th>
              <th scope="col" className={numCell}>{T.data.lanes.daily}</th>
              <th scope="col" className={numCell}>{T.data.lanes.request}</th>
              <th scope="col" className={numCell}>{T.data.runningCol}</th>
              <th scope="col" className={numCell}>{T.data.failed}</th>
            </tr>
          </thead>
          <tbody>
            {data.queue.by_kind.map((k) => (
              <tr key={k.kind}>
                <td>{T.data.kinds[k.kind] ?? k.kind}</td>
                <td className={numCell}>{formatNumber(k.pending)}</td>
                <td className={numCell}>{formatNumber(k.by_lane.load)}</td>
                <td className={numCell}>{formatNumber(k.by_lane.discovery)}</td>
                <td className={numCell}>{formatNumber(k.by_lane.daily)}</td>
                <td className={numCell}>{formatNumber(k.by_lane.request)}</td>
                <td className={numCell}>{formatNumber(k.running)}</td>
                <td className={numCell}>{formatNumber(k.failed)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.dailyCycle}>
        <h2>{T.data.dailyCycle}</h2>
        <Table caption={T.data.dailyCycle}>
          <thead>
            <tr>
              <th scope="col">{T.data.date}</th>
              <th scope="col">{T.data.status}</th>
              <th scope="col" className={numCell}>{T.data.lists}</th>
              <th scope="col" className={numCell}>{T.data.entries}</th>
            </tr>
          </thead>
          <tbody>
            {data.daily_cycle.map((d) => (
              <tr key={d.date}>
                <td>{formatDate(d.date)}</td>
                <td>{d.causelist_day?.status ?? "—"}</td>
                <td className={numCell}>{formatNumber(d.lists_stored)}</td>
                <td className={numCell}>{formatNumber(d.entries_parsed)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.masters}>
        <h2>{T.data.masters}</h2>
        <ul>
          {data.masters.map((m) => (
            <li key={m.master}>
              {m.master}: {formatDateTime(m.fetched_at)} ({formatNumber(m.row_count)})
            </li>
          ))}
        </ul>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.jobs}>
        <h2>{T.data.jobs}</h2>
        <ul>
          {data.jobs.map((j) => (
            <li key={j.job}>
              <span className="mono">{j.job}</span>: {j.status}, {formatDateTime(j.started_at)}
            </li>
          ))}
        </ul>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.mail}>
        <h2>{T.data.mail}</h2>
        <p>
          {formatNumber(data.mail.email_queued)} / {formatNumber(data.mail.email_failed)}
        </p>
      </section>
      <section className={`stack ${ds.panel}`} aria-label={T.data.openFailures}>
        <h2>{T.data.openFailures}</h2>
        <ul>
          {data.failures.map((f) => (
            <li key={f.kind}>
              <span className="mono">{f.kind}</span>: {formatNumber(f.open)}
            </li>
          ))}
        </ul>
      </section>
      <DocumentsTextBlock data={data.documents_text} />
    </>
  );
}

const TEXT_KINDS = ["order", "upload", "attachment"] as const;

/** Design document-ocr, decision 4: documents by text status, the ones not read split by type (totals only). */
function DocumentsTextBlock({ data }: { data: DataHealth["documents_text"] }) {
  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.documentsText}>
      <h2>{T.data.documentsText}</h2>
      <p className="muted">{T.data.documentsTextNote}</p>
      <Table caption={T.data.documentsText}>
        <thead>
          <tr>
            <th scope="col">{T.data.docKind}</th>
            <th scope="col" className={numCell}>{T.data.textPending}</th>
            <th scope="col" className={numCell}>{T.data.textExtracted}</th>
            <th scope="col" className={numCell}>{T.data.textFailed}</th>
            <th scope="col" className={numCell}>{T.data.textScannedPdf}</th>
            <th scope="col" className={numCell}>{T.data.textImage}</th>
            <th scope="col" className={numCell}>{T.data.textDoc}</th>
            <th scope="col" className={numCell}>{T.data.textOther}</th>
          </tr>
        </thead>
        <tbody>
          {TEXT_KINDS.map((kind) => {
            const k = data[kind];
            return (
              <tr key={kind}>
                <td>{T.data.docKinds[kind]}</td>
                <td className={numCell}>{formatNumber(k.pending)}</td>
                <td className={numCell}>{formatNumber(k.extracted)}</td>
                <td className={numCell}>{formatNumber(k.failed)}</td>
                <td className={numCell}>{formatNumber(k.none.scanned_pdf)}</td>
                <td className={numCell}>{formatNumber(k.none.image)}</td>
                <td className={numCell}>{formatNumber(k.none.doc)}</td>
                <td className={numCell}>{formatNumber(k.none.other)}</td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </section>
  );
}

type Pending = { path: string; body: Record<string, unknown>; text: string } | null;

function Buttons({ syncer, refetcher, checker }: { syncer: boolean; refetcher: boolean; checker: boolean }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const [warn, setWarn] = useState<Pending>(null);
  const [day, setDay] = useState("");
  const [caseRef, setCaseRef] = useState("");
  const [orderCase, setOrderCase] = useState({ case: "", order_id: "" });

  async function queue(path: string, body: Record<string, unknown>) {
    setMessage(null);
    setWarn(null);
    const out = await action.run(() =>
      api<QueueState>(path, { method: "POST", body }).catch((err) => {
        if (err instanceof ApiError && err.status === 409 && err.code === "already_held") {
          const text =
            path.endsWith("/day")
              ? T.data.dayHeld(String(err.extra.status ?? ""), Number(err.extra.lists_stored ?? 0))
              : T.data.caseHeld(formatDateTime(String(err.extra.dossier_fetched_at ?? "")));
          setWarn({ path, body, text });
          return null;
        }
        throw err;
      }),
    );
    if (out.ok && out.value) {
      setMessage(T.data.queued(T.data.kinds[out.value.kind] ?? out.value.kind, out.value.status ?? "—"));
      await queryClient.invalidateQueries({ queryKey: ["data-health"] });
    }
  }

  async function check() {
    setMessage(null);
    const out = await action.run(() => api<HealthCheck>("/admin/napix/health/check", { method: "POST" }));
    if (out.ok) setMessage(out.value.ok ? T.data.checkOk : T.data.checkFailed(out.value.error_family ?? "—"));
  }

  return (
    <section className={`stack ${ds.panel} ${ds.wide}`} aria-label={T.data.actions}>
      <h2>{T.data.actions}</h2>
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      <div className="actions">
        {syncer ? (
          <Button variant="secondary" busy={action.busy} onClick={() => queue("/admin/napix/sync-masters", {})}>
            {T.data.syncMasters}
          </Button>
        ) : null}
        {checker ? (
          <Button variant="secondary" busy={action.busy} onClick={check}>
            {T.data.check}
          </Button>
        ) : null}
      </div>
      {refetcher ? (
        <>
          <form
            className="row"
            aria-label={T.data.refetchDay}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void queue("/admin/napix/refetch/day", { date: day });
            }}
          >
            <TextField label={T.data.date} type="date" required value={day} onChange={(e) => setDay(e.target.value)} />
            <Button type="submit" variant="secondary" busy={action.busy}>
              {T.data.refetchDay}
            </Button>
          </form>
          <form
            className="row"
            aria-label={T.data.refetchCase}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void queue("/admin/napix/refetch/case", { case: caseRef.trim() });
            }}
          >
            <TextField label={T.data.caseRef} required value={caseRef} onChange={(e) => setCaseRef(e.target.value)} />
            <Button type="submit" variant="secondary" busy={action.busy}>
              {T.data.refetchCase}
            </Button>
          </form>
          <form
            className="row"
            aria-label={T.data.refetchOrder}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void queue("/admin/napix/refetch/order", { case: orderCase.case.trim(), order_id: orderCase.order_id.trim() });
            }}
          >
            <TextField label={T.data.caseRef} required value={orderCase.case} onChange={(e) => setOrderCase({ ...orderCase, case: e.target.value })} />
            <TextField label={T.data.orderId} required value={orderCase.order_id} onChange={(e) => setOrderCase({ ...orderCase, order_id: e.target.value })} />
            <Button type="submit" variant="secondary" busy={action.busy}>
              {T.data.refetchOrder}
            </Button>
          </form>
        </>
      ) : null}
      <Dialog open={warn !== null} title={T.data.heldTitle} onClose={() => setWarn(null)}>
        <p>{warn?.text}</p>
        <div className="actions">
          <Button busy={action.busy} onClick={() => warn && void queue(warn.path, { ...warn.body, force: true })}>
            {T.data.fetchAnyway}
          </Button>
          <Button variant="secondary" onClick={() => setWarn(null)}>
            {T.cancel}
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
