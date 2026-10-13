"use client";

/**
 * The data-load console (design data-load-console, decisions 6-12 and 19): the backdated load's status, the quota
 * window's allowance by lane (design napix-window: the window is detected, not the clock hour), work left, the estimate with its basis, failures, coverage month by month (on demand) and, for
 * `admin.data_load`, the actions: start a load (preview, then the choice for days already held), pause and resume,
 * what goes first, and fetching single cases from the court with the "already held" warning before any call.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CheckField,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  numCell,
  SelectField,
  Table,
  TextField,
  Tile,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type {
  CaseSearchItem,
  Coverage,
  CourtSearchOut,
  DataLoad,
  FetchDetails,
  HeldCase,
  LoadOrderOut,
  LoadPreview,
  LoadStart,
  QueueList,
  RetryFailed,
} from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

export const PROGRESS_KEY = ["data-load", "progress"] as const;
export const PROGRESS_POLL_MS = 30_000;
// the worker's probe interval while a reset is late (NAPIX_WINDOW_PROBE_SECONDS default; the health tab shows the set value)
const PROBE_MINUTES = 3;

export function LoadConsole() {
  const me = useMe();
  const progress = useQuery({
    queryKey: PROGRESS_KEY,
    queryFn: () => api<DataLoad>("/admin/data-load"),
    refetchInterval: PROGRESS_POLL_MS,
  });
  const manage = can(me.data, "admin.data_load");
  const retry = can(me.data, "admin.napix_refetch");
  return (
    <section className="stack" aria-label={T.data.title}>
      <ErrorBanner error={progress.error} onRetry={() => progress.refetch()} />
      {progress.isPending ? <Loading /> : null}
      {progress.data ? (
        <>
          <StatusBanner data={progress.data} />
          <AllowanceCard data={progress.data} />
          <WorkLeftTable data={progress.data} retry={retry} />
          <EstimateBlock data={progress.data} />
          <FailuresTable data={progress.data} />
        </>
      ) : null}
      <CoverageBlock />
      {manage && progress.data ? <ActionsPanel data={progress.data} /> : null}
    </section>
  );
}

function StatusBanner({ data }: { data: DataLoad }) {
  const st = data.settings;
  return (
    <div className="stack" aria-label={T.data.running}>
      <p>
        {st.paused ? <Badge tone="warning">{T.data.paused}</Badge> : <Badge tone="success">{T.data.running}</Badge>}{" "}
        {st.version > 0 && st.changed_by ? (
          <span className="muted">{T.data.changedBy(st.changed_by, formatDateTime(st.changed_at))}</span>
        ) : null}
      </p>
      {st.reason && st.version > 0 ? (
        <p className="muted">
          {T.data.reason}: {st.reason}
        </p>
      ) : null}
      <p className="muted">
        {T.data.switchApi(data.napix_enabled)} {T.data.switchNote}
      </p>
      <p>
        {data.period ? T.data.period(formatDate(data.period.from), formatDate(data.period.to)) : T.data.noPeriod}{" "}
        {st.load_order ? <span className="muted">({T.data.presets[st.load_order] ?? st.load_order})</span> : null}
      </p>
    </div>
  );
}

function AllowanceCard({ data }: { data: DataLoad }) {
  const a = data.allowance;
  return (
    <section className="stack" aria-label={T.data.allowance}>
      <h2>{T.data.allowance}</h2>
      <div className="row">
        {(["load", "discovery", "daily", "request", "outside_queue"] as const).map((lane) => (
          <Tile key={lane} label={T.data.lanes[lane] ?? lane} value={a.used[lane]} />
        ))}
      </div>
      <p>{a.remaining === null || a.remaining === undefined ? T.data.remainingUnknown : T.data.remaining(formatNumber(a.remaining))}</p>
      <p>{T.data.windowLine(a.window_status, formatTime(a.window_started_at), formatTime(a.next_reset_at), PROBE_MINUTES)}</p>
      <p className="muted">{T.data.thresholds(a.rate_reserve, a.live_reserve, a.search_floor)}</p>
    </section>
  );
}

function WorkLeftTable({ data, retry }: { data: DataLoad; retry: boolean }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  async function retryKind(kind: string) {
    const out = await action.run(() =>
      api<RetryFailed>("/admin/napix/queue/retry-failed", { method: "POST", body: { kind, lane: "load" } }),
    );
    if (out.ok) {
      setMessage(T.data.retried(out.value.retried));
      await queryClient.invalidateQueries({ queryKey: PROGRESS_KEY });
    }
  }
  return (
    <section className="stack" aria-label={T.data.workLeft}>
      <h2>{T.data.workLeft}</h2>
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      <Table caption={T.data.workLeft}>
        <thead>
          <tr>
            <th scope="col">{T.data.kind}</th>
            <th scope="col" className={numCell}>{T.data.pending}</th>
            <th scope="col" className={numCell}>{T.data.runnable}</th>
            <th scope="col" className={numCell}>{T.data.waiting}</th>
            <th scope="col" className={numCell}>{T.data.runningCol}</th>
            <th scope="col" className={numCell}>{T.data.failed}</th>
            {retry ? (
              <th scope="col">
                <span className="visually-hidden">{T.data.retryFailed}</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {data.work_left.map((w) => (
            <tr key={w.kind}>
              <td>{T.data.kinds[w.kind] ?? w.kind}</td>
              <td className={numCell}>{formatNumber(w.pending)}</td>
              <td className={numCell}>{formatNumber(w.runnable)}</td>
              <td className={numCell}>{formatNumber(w.waiting)}</td>
              <td className={numCell}>{formatNumber(w.running)}</td>
              <td className={numCell}>{formatNumber(w.failed)}</td>
              {retry ? (
                <td>
                  {w.failed > 0 ? (
                    <Button
                      variant="link"
                      busy={action.busy}
                      onClick={() => retryKind(w.kind)}
                      aria-label={`${T.data.retryFailed}: ${T.data.kinds[w.kind] ?? w.kind}`}
                    >
                      {T.data.retryFailed}
                    </Button>
                  ) : null}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}

function EstimateBlock({ data }: { data: DataLoad }) {
  const e = data.estimate;
  const basis = e.basis as Record<string, unknown>;
  let text: string;
  if (e.reason) text = T.data.estimateNone[e.reason] ?? e.reason;
  else if (e.calls_needed === 0) text = T.data.estimateDone;
  else text = T.data.estimateAt(formatDateTime(e.finish_at), formatNumber(e.hours ?? null));
  return (
    <section className="stack" aria-label={T.data.estimate}>
      <h2>{T.data.estimate}</h2>
      <p>{text}</p>
      {!e.reason && e.calls_needed ? (
        <details>
          <summary>{T.data.basis}</summary>
          <p>{T.data.callsNeeded(formatNumber(e.calls_needed))}</p>
          <p>{T.data.callsPerHour(formatNumber(Number(basis.calls_per_hour ?? 0)))}</p>
          <pre className="mono">{JSON.stringify(basis, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  );
}

function FailuresTable({ data }: { data: DataLoad }) {
  const rows = data.failures.latest;
  return (
    <section className="stack" aria-label={T.data.failures}>
      <h2>{T.data.failures}</h2>
      {rows.length === 0 ? (
        <EmptyState>{T.data.noFailures}</EmptyState>
      ) : (
        <Table caption={T.data.failures}>
          <thead>
            <tr>
              <th scope="col">{T.data.kind}</th>
              <th scope="col">{T.data.ref}</th>
              <th scope="col" className={numCell}>{T.data.attempts}</th>
              <th scope="col">{T.data.lastError}</th>
              <th scope="col">{T.data.at}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{T.data.kinds[r.kind] ?? r.kind}</td>
                <td className="mono">{r.ref}</td>
                <td className={numCell}>{r.attempts}</td>
                <td>{r.last_error ?? "—"}</td>
                <td>{formatDateTime(r.finished_at)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </section>
  );
}

function CoverageBlock() {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState<string | null>(null);
  const coverage = useQuery({
    queryKey: ["data-load", "coverage"],
    queryFn: () => api<Coverage>("/admin/data-load/coverage"),
    enabled: open,
  });
  const days = useQuery({
    queryKey: ["data-load", "days", month],
    queryFn: () => api<QueueList>("/admin/napix/queue", { query: { kind: "causelist_day", ref: month, limit: 31 } }),
    enabled: !!month,
  });
  return (
    <section className="stack" aria-label={T.data.coverage}>
      <h2>{T.data.coverage}</h2>
      {!open ? (
        <Button variant="secondary" onClick={() => setOpen(true)}>
          {T.data.loadCoverage}
        </Button>
      ) : null}
      {open && coverage.isPending ? <Loading /> : null}
      <ErrorBanner error={coverage.error} onRetry={() => coverage.refetch()} />
      {coverage.data ? (
        coverage.data.months.length === 0 ? (
          <EmptyState>{T.data.noPeriod}</EmptyState>
        ) : (
          <Table caption={T.data.coverage}>
            <thead>
              <tr>
                <th scope="col">{T.data.month}</th>
                <th scope="col" className={numCell}>{T.data.daysCovered}</th>
                <th scope="col" className={numCell}>{T.data.lists}</th>
                <th scope="col" className={numCell}>{T.data.entries}</th>
                <th scope="col" className={numCell}>{T.data.cases}</th>
                <th scope="col" className={numCell}>{T.data.details}</th>
                <th scope="col" className={numCell}>{T.data.orders}</th>
                <th scope="col" className={numCell}>{T.data.left}</th>
                <th scope="col" className={numCell}>{T.data.failed}</th>
                <th scope="col">
                  <span className="visually-hidden">{T.data.days}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {coverage.data.months.map((m) => (
                <tr key={m.month}>
                  <td className="mono">{m.month}</td>
                  <td className={numCell}>{`${m.days_covered_pct}%`}</td>
                  <td className={numCell}>{formatNumber(m.lists)}</td>
                  <td className={numCell}>{formatNumber(m.entries)}</td>
                  <td className={numCell}>{formatNumber(m.cases.listed)}</td>
                  <td className={numCell}>{m.details_pct === null ? "—" : `${m.details_pct}%`}</td>
                  <td className={numCell}>{`${formatNumber(m.orders.stored)} / ${formatNumber(m.orders.referenced)}`}</td>
                  <td className={numCell}>{formatNumber(m.work_left.causelist_day + m.work_left.dossier + m.work_left.order_pdf)}</td>
                  <td className={numCell}>{formatNumber(m.failed.causelist_day + m.failed.dossier + m.failed.order_pdf)}</td>
                  <td>
                    <Button variant="link" onClick={() => setMonth(m.month)} aria-label={`${T.data.days} ${m.month}`}>
                      {T.data.days}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )
      ) : null}
      {month && days.data ? (
        <Table caption={`${T.data.days} ${month}`}>
          <thead>
            <tr>
              <th scope="col">{T.data.date}</th>
              <th scope="col">{T.data.status}</th>
              <th scope="col">{T.data.lane}</th>
              <th scope="col" className={numCell}>{T.data.attempts}</th>
            </tr>
          </thead>
          <tbody>
            {days.data.items.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.ref}</td>
                <td>{r.status}</td>
                <td>{T.data.lanes[r.lane] ?? r.lane}</td>
                <td className={numCell}>{r.attempts}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ actions

function ActionsPanel({ data }: { data: DataLoad }) {
  return (
    <section className="stack" aria-label={T.data.actions}>
      <h2>{T.data.actions}</h2>
      <StartLoad />
      <PauseResume paused={data.settings.paused} />
      <OrderForm current={data.settings.load_order} />
      <FetchFromCourt />
    </section>
  );
}

function StartLoad() {
  const queryClient = useQueryClient();
  const action = useAction();
  const [range, setRange] = useState({ from: "", to: "" });
  const [preview, setPreview] = useState<LoadPreview | null>(null);
  const [held, setHeld] = useState<"skip" | "refetch">("skip");
  const [message, setMessage] = useState<string | null>(null);
  const heldDays = preview ? preview.held_with_lists + preview.held_no_list : 0;

  async function doPreview(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    const out = await action.run(() =>
      api<LoadPreview>("/admin/data-load/preview", { method: "POST", body: { from: range.from, to: range.to } }),
    );
    if (out.ok) setPreview(out.value);
  }

  async function doStart() {
    const out = await action.run(() =>
      api<LoadStart>("/admin/data-load/start", {
        method: "POST",
        body: { from: range.from, to: range.to, ...(heldDays > 0 ? { held } : {}) },
      }),
    );
    if (out.ok) {
      setMessage(T.data.started(out.value.queued + out.value.revived + out.value.held_requeued));
      setPreview(null);
      await queryClient.invalidateQueries({ queryKey: ["data-load"] });
    }
  }

  return (
    <form className="stack" onSubmit={doPreview} aria-label={T.data.start}>
      <h3>{T.data.start}</h3>
      <div className="row">
        <TextField label={T.data.from} type="date" required value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} />
        <TextField label={T.data.to} type="date" required value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} />
        <Button type="submit" variant="secondary" busy={action.busy}>
          {T.data.preview}
        </Button>
      </div>
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      {preview ? (
        <div className="stack">
          <p>{T.data.previewText(preview.days, heldDays, preview.waiting, preview.failed, preview.not_queued)}</p>
          <p className="muted">
            {preview.calls_estimate === null || preview.calls_estimate === undefined
              ? T.data.callsEstimateNone
              : T.data.callsEstimate(formatNumber(preview.calls_estimate))}
          </p>
          {preview.masters_stale ? <p className="muted">{T.data.mastersStale}</p> : null}
          {heldDays > 0 ? (
            <SelectField
              label={T.data.heldChoice}
              value={held}
              onChange={(e) => setHeld(e.target.value as "skip" | "refetch")}
              options={[
                { value: "skip", label: T.data.heldSkip },
                { value: "refetch", label: T.data.heldRefetch },
              ]}
            />
          ) : null}
          <Button busy={action.busy} onClick={doStart}>
            {T.data.startNow}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

function PauseResume({ paused }: { paused: boolean }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [reason, setReason] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      paused
        ? api("/admin/data-load/resume", { method: "POST", body: {} })
        : api("/admin/data-load/pause", { method: "POST", body: { reason: reason.trim() } }),
    );
    if (out.ok) {
      setReason("");
      await queryClient.invalidateQueries({ queryKey: PROGRESS_KEY });
    }
  }
  return (
    <form className="stack" onSubmit={submit} aria-label={paused ? T.data.resume : T.data.pause}>
      <h3>{paused ? T.data.resume : T.data.pause}</h3>
      {!paused ? (
        <TextField
          label={T.data.pauseReason}
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      ) : null}
      <ErrorBanner error={action.error} />
      <div>
        <Button type="submit" variant={paused ? "primary" : "danger"} busy={action.busy} disabled={!paused && reason.trim().length < 3}>
          {paused ? T.data.resume : T.data.pause}
        </Button>
      </div>
    </form>
  );
}

function OrderForm({ current }: { current: string }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [form, setForm] = useState({ load_order: current, first_from: "", first_to: "", reason: "" });
  const [message, setMessage] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      api<LoadOrderOut>("/admin/data-load/order", {
        method: "PUT",
        body: {
          load_order: form.load_order,
          first_from: form.first_from || null,
          first_to: form.first_to || null,
          reason: form.reason.trim(),
        },
      }),
    );
    if (out.ok) {
      setMessage(T.data.orderSaved(out.value.reprioritised));
      await queryClient.invalidateQueries({ queryKey: PROGRESS_KEY });
    }
  }
  return (
    <form className="stack" onSubmit={submit} aria-label={T.data.order}>
      <h3>{T.data.order}</h3>
      <div className="row">
        <SelectField
          label={T.data.preset}
          value={form.load_order}
          onChange={(e) => setForm({ ...form, load_order: e.target.value })}
          options={Object.entries(T.data.presets).map(([value, label]) => ({ value, label }))}
        />
        <TextField label={T.data.firstFrom} type="date" value={form.first_from} onChange={(e) => setForm({ ...form, first_from: e.target.value })} />
        <TextField label={T.data.firstTo} type="date" value={form.first_to} onChange={(e) => setForm({ ...form, first_to: e.target.value })} />
      </div>
      <TextField
        label={T.data.orderReason}
        required
        minLength={3}
        maxLength={500}
        value={form.reason}
        onChange={(e) => setForm({ ...form, reason: e.target.value })}
      />
      <ErrorBanner error={action.error} />
      {message ? <Notice>{message}</Notice> : null}
      <div>
        <Button type="submit" busy={action.busy} disabled={form.reason.trim().length < 3}>
          {T.save}
        </Button>
      </div>
    </form>
  );
}

type FetchForm = {
  kind: "cnr" | "case_number" | "party";
  cnr: string;
  case_type: string;
  reg_no: string;
  reg_year: string;
  name: string;
  pend_disp: "P" | "D" | "both";
};

type Warning =
  | { code: "already_held"; cases: HeldCase[] }
  | { code: "searched_before"; at: string; stored: number; local: number };

function fetchBody(f: FetchForm, force: boolean): Record<string, unknown> {
  if (f.kind === "cnr") return { kind: "cnr", cnr: f.cnr.trim().toUpperCase(), force };
  if (f.kind === "case_number")
    return { kind: "case_number", case_type: f.case_type.trim(), reg_no: Number(f.reg_no), reg_year: Number(f.reg_year), force };
  return { kind: "party", name: f.name.trim(), reg_year: Number(f.reg_year), pend_disp: f.pend_disp, force };
}

export function FetchFromCourt() {
  const queryClient = useQueryClient();
  const action = useAction();
  const details = useAction();
  const [form, setForm] = useState<FetchForm>({
    kind: "cnr",
    cnr: "",
    case_type: "",
    reg_no: "",
    reg_year: "",
    name: "",
    pend_disp: "P",
  });
  const [warning, setWarning] = useState<Warning | null>(null);
  const [result, setResult] = useState<CourtSearchOut | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [detailOut, setDetailOut] = useState<FetchDetails | null>(null);

  async function send(force: boolean) {
    setWarning(null);
    setDetailOut(null);
    const out = await action.run(() =>
      api<CourtSearchOut>("/admin/data-load/fetch", { method: "POST", body: fetchBody(form, force) }).catch((err) => {
        if (err instanceof ApiError && err.status === 409 && err.code === "already_held") {
          setWarning({ code: "already_held", cases: (err.extra.cases as HeldCase[]) ?? [] });
          return null;
        }
        if (err instanceof ApiError && err.status === 409 && err.code === "searched_before") {
          setWarning({
            code: "searched_before",
            at: String(err.extra.last_searched_at ?? ""),
            stored: Number(err.extra.stored ?? 0),
            local: Number(err.extra.local_matches ?? 0),
          });
          return null;
        }
        throw err;
      }),
    );
    if (out.ok && out.value) {
      setResult(out.value);
      setPicked([]);
      await queryClient.invalidateQueries({ queryKey: PROGRESS_KEY });
    }
  }

  async function fetchDetails() {
    const out = await details.run(() =>
      api<FetchDetails>("/admin/data-load/fetch-details", { method: "POST", body: { cases: picked, force: false } }),
    );
    if (out.ok) setDetailOut(out.value);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send(false);
  }

  const items: CaseSearchItem[] = result?.items ?? [];
  return (
    <form className="stack" onSubmit={submit} aria-label={T.data.fetch}>
      <h3>{T.data.fetch}</h3>
      <div className="row">
        <SelectField
          label={T.data.fetchKind}
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value as FetchForm["kind"] })}
          options={[
            { value: "cnr", label: T.data.byCnr },
            { value: "case_number", label: T.data.byNumber },
            { value: "party", label: T.data.byParty },
          ]}
        />
        {form.kind === "cnr" ? (
          <TextField label={T.data.cnr} required value={form.cnr} onChange={(e) => setForm({ ...form, cnr: e.target.value })} />
        ) : null}
        {form.kind === "case_number" ? (
          <>
            <TextField label={T.data.caseType} required value={form.case_type} onChange={(e) => setForm({ ...form, case_type: e.target.value })} />
            <TextField label={T.data.regNo} type="number" required value={form.reg_no} onChange={(e) => setForm({ ...form, reg_no: e.target.value })} />
          </>
        ) : null}
        {form.kind === "party" ? (
          <>
            <TextField label={T.data.party} required minLength={3} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <SelectField
              label={T.data.pendDisp}
              value={form.pend_disp}
              onChange={(e) => setForm({ ...form, pend_disp: e.target.value as FetchForm["pend_disp"] })}
              options={Object.entries(T.data.pendDispOptions).map(([value, label]) => ({ value, label }))}
            />
          </>
        ) : null}
        {form.kind !== "cnr" ? (
          <TextField label={T.data.regYear} type="number" required value={form.reg_year} onChange={(e) => setForm({ ...form, reg_year: e.target.value })} />
        ) : null}
        <Button type="submit" busy={action.busy}>
          {T.data.fetchNow}
        </Button>
      </div>
      <ErrorBanner error={action.error} />
      <Dialog
        open={warning !== null}
        title={warning?.code === "searched_before" ? T.data.searchedTitle : T.data.heldTitle}
        onClose={() => setWarning(null)}
      >
        {warning?.code === "already_held" ? (
          <div className="stack">
            <p>{T.data.heldText}</p>
            <ul>
              {warning.cases.map((c) => (
                <li key={c.case.id}>{T.data.heldWhen(c.case.ref_no, formatDateTime(c.dossier_fetched_at), c.dossier_stale)}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {warning?.code === "searched_before" ? (
          <p>{T.data.searchedText(formatDateTime(warning.at), warning.stored, warning.local)}</p>
        ) : null}
        <div className="actions">
          <Button busy={action.busy} onClick={() => void send(true)}>
            {T.data.fetchAnyway}
          </Button>
          <Button variant="secondary" onClick={() => setWarning(null)}>
            {T.cancel}
          </Button>
        </div>
      </Dialog>
      {result ? (
        <div className="stack" aria-label={T.data.results}>
          <h4>{T.data.results}</h4>
          {items.length === 0 ? (
            <EmptyState>{T.data.noDuplicates}</EmptyState>
          ) : (
            <Table caption={T.data.results}>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">{T.data.fetchDetails}</span>
                  </th>
                  <th scope="col">{T.data.case}</th>
                  <th scope="col">{T.data.cnr}</th>
                  <th scope="col">{T.data.details}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.case.id}>
                    <td>
                      <CheckField
                        label={<span className="visually-hidden">{it.case.ref_no}</span>}
                        checked={picked.includes(it.case.ref_no)}
                        onChange={(e) =>
                          setPicked(e.target.checked ? [...picked, it.case.ref_no] : picked.filter((r) => r !== it.case.ref_no))
                        }
                      />
                    </td>
                    <td>
                      <span className="mono">{it.case.case_no_text ?? it.case.ref_no}</span>{" "}
                      {!it.visible ? <span className="muted">({T.data.notVisible})</span> : null}
                    </td>
                    <td className="mono">{it.case.cnr ?? "—"}</td>
                    <td>{it.dossier_status}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {items.length > 0 ? (
            <div>
              <Button variant="secondary" busy={details.busy} disabled={picked.length === 0} onClick={fetchDetails}>
                {T.data.fetchDetails}
              </Button>
            </div>
          ) : null}
          <ErrorBanner error={details.error} />
          {detailOut ? (
            <Notice>{T.data.detailsQueued(detailOut.items.filter((i) => i.state === "queued").length)}</Notice>
          ) : null}
          {detailOut ? (
            <ul>
              {detailOut.items.map((i) => (
                <li key={i.ref}>
                  <span className="mono">{i.ref}</span>: {T.data.detailStates[i.state] ?? i.state}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
