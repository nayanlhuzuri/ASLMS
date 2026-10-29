"use client";

/**
 * Automatic Collection (design data-collection-redesign, decisions 34-41): Load Control for the past-months collection
 * (Start, Pause and Resume in dialogs; Start Load only when something would be fetched), what is waiting, What Goes
 * First on a three-column grid, the Court Allowance with Calls by Person for the operators (the API decides), the
 * daily schedule and the daily updates of the last 7 days in plain words, and Search by Department Names. The page's
 * one primary is Start a Load; every action needs `admin.data_load` and the API decides. No GET calls the court.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  DefinitionList,
  Dialog,
  EmptyState,
  ErrorBanner,
  Kpi,
  Loading,
  Notice,
  ProgressBar,
  RadioGroup,
  ScrollBox,
  SelectField,
  TabToolbar,
  TextField,
  useSecondsSince,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DataLoad, DiscoverySummary, DiscoverySweep, LoadOrderOut, LoadPreview, LoadStart, NapixHealth } from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import { dailyStatus, DC_KEYS, minutesToReset, POLL, PROBLEM_LINKS, type DataSchedule } from "@/lib/dataCollection";
import { formatDate, formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";
import { usePulse } from "./Overview";

const n = (v: number | null | undefined) => formatNumber(v ?? 0);
const LANES = ["load", "daily", "discovery", "request", "outside_queue"] as const;
const DISCOVERY_KEY = ["data-discovery"] as const;

export function AutomaticCollection() {
  const me = useMe();
  const progress = useQuery({
    queryKey: DC_KEYS.progress,
    queryFn: () => api<DataLoad>("/admin/data-load"),
    refetchInterval: POLL.overview,
    refetchIntervalInBackground: false,
  });
  const manage = can(me.data, "admin.data_load");
  return (
    <div className="stack">
      <TabToolbar updatedAt={progress.dataUpdatedAt || null} />
      <ErrorBanner error={progress.error} onRetry={() => progress.refetch()} />
      {progress.isPending ? <Loading lines={6} /> : null}
      {progress.data ? <LoadControl data={progress.data} manage={manage} /> : null}
      <div className={ds.board}>
        {progress.data ? <OrderCard data={progress.data} manage={manage} /> : null}
        {progress.data ? <AllowanceCard data={progress.data} /> : null}
      </div>
      <ScheduleCards />
      <DepartmentNames />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ Load Control

function LoadControl({ data, manage }: { data: DataLoad; manage: boolean }) {
  const [dialog, setDialog] = useState<"start" | "pause" | "resume" | null>(null);
  const st = data.settings;
  const left = Object.fromEntries(data.work_left.map((w) => [w.kind, w.pending + w.running]));
  const failed = data.work_left.reduce((sum, w) => sum + w.failed, 0);
  return (
    <section className={ds.panel} aria-labelledby="dc-load-control">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="dc-load-control" title={T.dc.pastMonthsTooltip}>
            {T.dc.loadControlTitle}: {T.dc.pastMonths}
          </h2>
          {manage ? (
            <div className="actions">
              {st.paused ? (
                <Button variant="secondary" onClick={() => setDialog("resume")}>
                  {T.dc.resumeButton}
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => setDialog("pause")}>
                  {T.dc.pauseButton}
                </Button>
              )}
              <Button onClick={() => setDialog("start")}>{T.dc.startButton}</Button>
            </div>
          ) : null}
        </div>
        <p className={ds.line}>{T.dc.pastMonthsIntro}</p>
        <DefinitionList
          items={[
            [
              T.dc.facts.status,
              <Badge key="s" tone={st.paused ? "warning" : "info"}>
                {st.paused ? T.dc.states.paused : T.dc.states.running}
              </Badge>,
            ],
            [T.dc.facts.since, st.version > 0 ? formatDateTime(st.changed_at) : null],
            [T.dc.facts.reason, st.version > 0 ? st.reason : null],
            [T.dc.facts.period, data.period ? `${formatDate(data.period.from)} – ${formatDate(data.period.to)}` : T.dc.noPeriodNote],
            [T.dc.facts.order, T.data.presets[st.load_order] ?? st.load_order],
            [T.dc.facts.connection, data.napix_enabled ? T.dc.connectionOn : T.dc.connectionOff],
          ]}
        />
        <p className={ds.line}>
          {T.dc.waitingLine(n(left.causelist_day), n(left.dossier), n(left.order_pdf))}
          {failed > 0 ? (
            <>
              {" · "}
              <Link href={PROBLEM_LINKS.failed!}>{T.dc.failedLink(n(failed))}</Link>
            </>
          ) : null}
        </p>
        {!manage ? <p className={ds.line}>{T.dc.readOnlyNote}</p> : null}
      </div>
      {dialog === "start" ? <StartDialog data={data} onClose={() => setDialog(null)} /> : null}
      {dialog === "pause" ? <PauseDialog onClose={() => setDialog(null)} /> : null}
      {dialog === "resume" ? <ResumeDialog onClose={() => setDialog(null)} /> : null}
    </section>
  );
}

/** Decision 36: Start a Load in a dialog; Start Load appears only when something would be fetched. */
export function StartDialog({ data, onClose }: { data: DataLoad; onClose: () => void }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [range, setRange] = useState({ from: "", to: "" });
  const [preview, setPreview] = useState<LoadPreview | null>(null);
  const [held, setHeld] = useState<"skip" | "refetch">("skip");
  const [message, setMessage] = useState<string | null>(null);
  const heldDays = preview ? preview.held_with_lists + preview.held_no_list : 0;
  const fresh = preview ? preview.not_queued + preview.failed : 0;
  const wouldFetch = !!preview && (fresh > 0 || (heldDays > 0 && held === "refetch"));
  const perHour = Number((data.estimate.basis as Record<string, unknown>).calls_per_hour ?? 0);

  async function check(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    const out = await action.run(() =>
      api<LoadPreview>("/admin/data-load/preview", { method: "POST", body: { from: range.from, to: range.to } }),
    );
    if (out.ok) setPreview(out.value);
  }

  async function start() {
    const out = await action.run(() =>
      api<LoadStart>("/admin/data-load/start", {
        method: "POST",
        body: { from: range.from, to: range.to, ...(heldDays > 0 ? { held } : {}) },
      }),
    );
    if (out.ok) {
      setMessage(T.dc.startedNote(out.value.queued + out.value.revived + out.value.held_requeued));
      setPreview(null);
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
    }
  }

  const calls = preview?.calls_estimate;
  return (
    <Dialog
      open
      wide
      title={T.dc.startTitle}
      onClose={onClose}
      footer={
        <div className="actions">
          <Button variant="secondary" onClick={onClose}>
            {T.dc.close}
          </Button>
          {wouldFetch ? (
            <Button busy={action.busy} onClick={() => void start()}>
              {T.dc.startLoad}
            </Button>
          ) : null}
        </div>
      }
    >
      <form className="stack" onSubmit={check} aria-label={T.dc.checkDates}>
        <div className="row">
          <TextField
            label={T.data.from}
            type="date"
            required
            value={range.from}
            onChange={(e) => (setRange({ ...range, from: e.target.value }), setPreview(null))}
          />
          <TextField
            label={T.data.to}
            type="date"
            required
            value={range.to}
            onChange={(e) => (setRange({ ...range, to: e.target.value }), setPreview(null))}
          />
          <Button type="submit" variant="secondary" busy={action.busy}>
            {T.dc.checkDates}
          </Button>
        </div>
        <ErrorBanner error={action.error} />
        {message ? <Notice>{message}</Notice> : null}
        {preview ? (
          <div className="stack">
            <div className={ds.previewTiles}>
              <Kpi label={T.dc.previewTiles.days!} value={preview.days} />
              <Kpi label={T.dc.previewTiles.held!} value={heldDays} />
              <Kpi label={T.dc.previewTiles.waiting!} value={preview.waiting} />
              <Kpi label={T.dc.previewTiles.failed!} value={preview.failed} />
              <Kpi label={T.dc.previewTiles.fresh!} value={preview.not_queued} />
            </div>
            {calls === null || calls === undefined ? (
              <p className={ds.line}>{T.dc.previewNoCallsNote}</p>
            ) : (
              <p className={ds.line}>
                {T.dc.previewCalls(n(calls), perHour > 0 ? formatNumber(Math.round((calls / perHour) * 10) / 10) : null)}
              </p>
            )}
            {preview.masters_stale ? <p className={ds.line}>{T.dc.mastersStaleNote}</p> : null}
            {heldDays > 0 ? (
              <RadioGroup
                legend={T.dc.heldLegend}
                name="held"
                value={held}
                onChange={(v) => setHeld(v as "skip" | "refetch")}
                options={[
                  { value: "skip", label: T.dc.heldSkip },
                  { value: "refetch", label: T.dc.heldRefetch },
                ]}
              />
            ) : null}
            {!wouldFetch ? <Notice>{T.dc.nothingNewNote}</Notice> : null}
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}

/** Decision 36: Pause needs a reason of 3 to 500 characters; its button is a danger button. */
export function PauseDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [reason, setReason] = useState("");
  const ok = reason.trim().length >= 3 && reason.trim().length <= 500;
  async function pause() {
    const out = await action.run(() => api("/admin/data-load/pause", { method: "POST", body: { reason: reason.trim() } }));
    if (out.ok) {
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open
      title={T.dc.pauseTitle}
      onClose={onClose}
      onConfirm={() => void pause()}
      busy={action.busy}
      error={action.error}
      confirmLabel={T.dc.pauseConfirm}
      confirmDisabled={!ok}
      danger
    >
      <TextField
        label={T.dc.pauseReasonLabel}
        hint={T.dc.pauseReasonHint}
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
    </ConfirmDialog>
  );
}

function ResumeDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const action = useAction();
  async function resume() {
    const out = await action.run(() => api("/admin/data-load/resume", { method: "POST", body: {} }));
    if (out.ok) {
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open
      title={T.dc.resumeTitle}
      onClose={onClose}
      onConfirm={() => void resume()}
      busy={action.busy}
      error={action.error}
      confirmLabel={T.dc.resumeConfirm}
    >
      <p>{T.dc.resumeNote}</p>
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------------------------------------ What Goes First

/** Decision 37: the select and the "Bring These Dates Forward" fieldset on row 1, the reason and Save on row 2. */
export function OrderCard({ data, manage }: { data: DataLoad; manage: boolean }) {
  const queryClient = useQueryClient();
  const action = useAction();
  const st = data.settings;
  const [form, setForm] = useState({ load_order: st.load_order, first_from: "", first_to: "", reason: "" });
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
      setMessage(T.dc.orderSaved(out.value.reprioritised));
      setForm({ ...form, reason: "" });
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
    }
  }
  const now = T.dc.orderNow(
    T.data.presets[st.load_order] ?? st.load_order,
    st.first_from ? formatDate(st.first_from) : null,
    st.first_to ? formatDate(st.first_to) : null,
  );
  return (
    <section className={ds.panel} aria-labelledby="dc-order">
      <div className="stack">
        <h2 id="dc-order">{T.dc.orderTitle}</h2>
        {manage ? (
          <form className="stack" onSubmit={submit} aria-label={T.dc.orderTitle}>
            <div className={ds.orderGrid}>
              <SelectField
                label={T.dc.orderSelectLabel}
                value={form.load_order}
                onChange={(e) => setForm({ ...form, load_order: e.target.value })}
                options={Object.entries(T.data.presets).map(([value, label]) => ({ value, label }))}
              />
              <fieldset>
                <legend>{T.dc.forwardLegend}</legend>
                <TextField
                  label={T.dc.forwardFrom}
                  type="date"
                  value={form.first_from}
                  onChange={(e) => setForm({ ...form, first_from: e.target.value })}
                />
                <TextField
                  label={T.dc.forwardTo}
                  type="date"
                  value={form.first_to}
                  onChange={(e) => setForm({ ...form, first_to: e.target.value })}
                />
              </fieldset>
              <div className={ds.span2}>
                <TextField
                  label={T.dc.orderReasonLabel}
                  required
                  minLength={3}
                  maxLength={500}
                  value={form.reason}
                  onChange={(e) => setForm({ ...form, reason: e.target.value })}
                />
              </div>
              <div className={ds.control}>
                <Button type="submit" variant="secondary" busy={action.busy} disabled={form.reason.trim().length < 3}>
                  {T.dc.savePriority}
                </Button>
              </div>
            </div>
            <ErrorBanner error={action.error} />
            {message ? <Notice>{message}</Notice> : null}
          </form>
        ) : null}
        <p className={ds.line}>{now}</p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ Court Allowance

function AllowanceCard({ data }: { data: DataLoad }) {
  const me = useMe();
  const pulse = usePulse(POLL.overview);
  const operator = canAny(me.data, ["admin.napix_refetch", "admin.masters_sync"]);
  const health = useQuery({
    queryKey: ["data-health", "napix"],
    queryFn: () => api<NapixHealth>("/admin/napix/health"),
    enabled: operator,
    refetchInterval: POLL.months,
    refetchIntervalInBackground: false,
  });
  const since = useSecondsSince(pulse.dataUpdatedAt || null);
  const a = data.allowance;
  const w = pulse.data?.window;
  const used = LANES.reduce((sum, lane) => sum + (a.used[lane] ?? 0), 0);
  const limit = w?.hourly_limit ?? null;
  const minutes = w ? minutesToReset(w.seconds_to_next_reset, pulse.dataUpdatedAt, pulse.dataUpdatedAt + (since ?? 0) * 1000) : null;
  const byUser = health.data?.by_user?.window;
  return (
    <section className={ds.panel} aria-labelledby="dc-allowance">
      <div className="stack">
        <h2 id="dc-allowance">{T.dc.allowanceTitle}</h2>
        <ProgressBar
          label={T.dc.callsThisHour}
          max={limit ?? Math.max(used, 1)}
          segments={[{ tone: "active", value: used }]}
          text={limit ? T.dc.callsBar(n(used), n(limit)) : T.dc.callsBarNoLimit(n(used))}
        />
        <DefinitionList
          items={[
            [T.dc.callsLeft, a.remaining === null || a.remaining === undefined ? T.dc.unknown : n(a.remaining)],
            [
              T.dc.nextReset,
              a.next_reset_at
                ? `${formatTime(a.next_reset_at)}${minutes !== null ? ` (${T.dc.nextResetIn(minutes)})` : ""}`
                : T.dc.unknown,
            ],
          ]}
        />
        <h3>{T.dc.byKindTitle}</h3>
        <DataTable
          caption={T.dc.byKindTitle}
          rows={[...LANES]}
          rowKey={(lane) => lane}
          columns={[
            { key: "lane", header: T.dc.cols.kindOfWork, primary: true, cell: (lane) => T.dc.lanes[lane] ?? lane },
            { key: "calls", header: T.dc.cols.calls, align: "right", cell: (lane) => n(a.used[lane]) },
          ]}
        />
        {byUser ? (
          <>
            <h3>{T.dc.byPersonTitle}</h3>
            {byUser.length === 0 ? (
              <p className={ds.line}>{T.dc.noPersonCallsNote}</p>
            ) : (
              <DataTable
                caption={T.dc.byPersonTitle}
                rows={byUser}
                rowKey={(u) => u.user_id}
                columns={[
                  { key: "user", header: T.dc.cols.person, primary: true, cell: (u) => u.name },
                  { key: "calls", header: T.dc.cols.calls, align: "right", cell: (u) => n(u.calls) },
                  { key: "failed", header: T.dc.cols.callsFailed, align: "right", cell: (u) => n(u.failed) },
                ]}
              />
            )}
          </>
        ) : null}
        <p className={ds.line}>{T.dc.allowanceHint(a.rate_reserve, a.live_reserve, a.search_floor)}</p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ the schedule

function ScheduleCards() {
  const schedule = useQuery({
    queryKey: DC_KEYS.schedule,
    queryFn: () => api<DataSchedule>("/admin/data-load/schedule"),
    refetchInterval: POLL.months,
    refetchIntervalInBackground: false,
  });
  const facts = (e: DataSchedule["entries"][number]): string | null => {
    const f = e.facts as Record<string, number | null | undefined>;
    if (e.key === "disposed-refresh" && f.eligible !== undefined) return T.dc.scheduleFacts.disposed(n(f.eligible), n(f.due_now));
    if (e.key === "purge" && f.deleted !== undefined && f.deleted !== null) return T.dc.scheduleFacts.purge(n(f.deleted));
    return null;
  };
  return (
    <>
      <section className={ds.panel} aria-labelledby="dc-schedule">
        <div className="stack">
          <h2 id="dc-schedule">{T.dc.scheduleTitle}</h2>
          <ErrorBanner error={schedule.error} onRetry={() => schedule.refetch()} />
          {schedule.isPending ? <Loading /> : null}
          {schedule.data ? (
            <DataTable
              caption={T.dc.scheduleTitle}
              rows={schedule.data.entries}
              rowKey={(e) => e.key}
              columns={[
                { key: "when", header: T.dc.cols.when, width: "140px", cell: (e) => e.when },
                {
                  key: "what",
                  header: T.dc.cols.what,
                  primary: true,
                  cell: (e) => {
                    const extra = facts(e);
                    return extra ? `${e.what} (${extra})` : e.what;
                  },
                },
                {
                  key: "last",
                  header: T.dc.cols.lastRun,
                  cell: (e) => (e.last_run_at ? formatDateTime(e.last_run_at) : <span className={ds.muted}>{T.dc.notRecorded}</span>),
                },
                {
                  key: "result",
                  header: T.dc.cols.result,
                  cell: (e) =>
                    e.result ? (
                      <Badge tone={e.result === "succeeded" ? "success" : e.result === "failed" ? "danger" : undefined}>
                        {T.dc.results[e.result] ?? e.result}
                      </Badge>
                    ) : (
                      "—"
                    ),
                },
              ]}
            />
          ) : null}
        </div>
      </section>
      <section className={ds.panel} aria-labelledby="dc-daily">
        <div className="stack">
          <h2 id="dc-daily">{T.dc.dailyTitle}</h2>
          {schedule.data ? (
            <DataTable
              caption={T.dc.dailyTitle}
              rows={[...schedule.data.daily_cycle].reverse()}
              rowKey={(d) => d.date}
              columns={[
                { key: "date", header: T.dc.cols.date, primary: true, cell: (d) => formatDate(d.date) },
                { key: "status", header: T.dc.cols.status, cell: (d) => dailyStatus(d) },
                { key: "lists", header: T.dc.cols.lists, align: "right", cell: (d) => n(d.lists_stored) },
                { key: "entries", header: T.dc.cols.entries, align: "right", cell: (d) => n(d.entries_parsed) },
                { key: "corrected", header: T.dc.cols.corrected, align: "right", cell: (d) => n(d.lists_corrected) },
                {
                  key: "recheck",
                  header: T.dc.cols.recheck,
                  cell: (d) => (d.recheck ? (T.dc.recheckStates[d.recheck.status] ?? d.recheck.status) : "—"),
                },
              ]}
            />
          ) : null}
        </div>
      </section>
    </>
  );
}

// ------------------------------------------------------------------------------------------------ department names

/** Decision 41: today's Discovery, renamed, with its empty state while no name is registered. */
export function DepartmentNames() {
  const me = useMe();
  const queryClient = useQueryClient();
  const action = useAction();
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const data = useQuery({ queryKey: DISCOVERY_KEY, queryFn: () => api<DiscoverySummary>("/admin/discovery") });
  async function sweep() {
    const out = await action.run(() => api<DiscoverySweep>("/admin/discovery/sweep", { method: "POST", body: {} }));
    if (out.ok) {
      setConfirm(false);
      setMessage(T.discovery.swept(out.value.rows_queued, out.value.terms));
      await queryClient.invalidateQueries({ queryKey: DISCOVERY_KEY });
    }
  }
  const d = data.data;
  const names = d ? d.terms.active + d.terms.inactive : 0;
  return (
    <section className={ds.panel} id="department-names" aria-labelledby="dc-names">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="dc-names">{T.dc.namesTitle}</h2>
          {d && names > 0 && can(me.data, "admin.data_load") ? (
            <Button variant="secondary" onClick={() => setConfirm(true)}>
              {T.dc.sweepButton}
            </Button>
          ) : null}
        </div>
        <p className={ds.line}>{T.dc.namesIntro}</p>
        {data.isPending ? <Loading /> : null}
        <ErrorBanner error={data.error} onRetry={() => data.refetch()} />
        {message ? <Notice>{message}</Notice> : null}
        {d && names === 0 ? (
          <EmptyState>
            <p>{T.dc.namesEmpty}</p>
            {can(me.data, "admin.keywords") ? <Link href="/admin/mapping/keywords">{T.dc.namesMappingLink}</Link> : null}
          </EmptyState>
        ) : null}
        {d && names > 0 ? (
          <>
            <div className={ds.kpis}>
              <Kpi label={T.dc.namesTiles.searched!} value={d.terms.active} />
              <Kpi label={T.dc.namesTiles.paused!} value={d.terms.inactive} />
              <Kpi label={T.dc.namesTiles.found!} value={d.cases.found} />
              <Kpi label={T.dc.namesTiles.created!} value={d.cases.created_by_discovery} />
              <Kpi label={T.dc.namesTiles.recommended!} value={d.cases.recommended_from_discovery} />
            </div>
            {d.settings.share === 0 ? (
              <p className={ds.line}>{T.dc.shareOffNote}</p>
            ) : (
              <ProgressBar
                size="sm"
                label={T.dc.namesTitle}
                max={d.settings.share}
                segments={[{ tone: "active", value: d.window.discovery_calls }]}
                text={T.dc.shareBar(n(d.window.discovery_calls), n(d.settings.share))}
              />
            )}
            <p className={ds.line}>{T.dc.namesFromYear(d.settings.from_year)}</p>
            <p className={ds.line}>
              {T.dc.namesWaiting(
                n(d.queue.by_kind.party_search.pending),
                n(d.queue.by_kind.dossier.pending),
                n(d.queue.by_kind.order_pdf.pending),
              )}
            </p>
            {d.latest_failures.length > 0 ? (
              <ScrollBox label={T.discovery.failures}>
                <DataTable
                  caption={T.discovery.failures}
                  showCaption
                  rows={d.latest_failures}
                  rowKey={(f) => `${f.kind}:${f.ref}`}
                  columns={[
                    { key: "kind", header: T.dc.cols.kindOfWork, cell: (f) => T.dc.kinds[f.kind] ?? f.kind },
                    { key: "ref", header: T.data.ref, primary: true, cell: (f) => <span className="mono">{f.ref}</span> },
                    { key: "error", header: T.data.lastError, cell: (f) => f.last_error ?? "—" },
                    { key: "at", header: T.dc.cols.when, cell: (f) => formatDateTime(f.finished_at) },
                  ]}
                />
              </ScrollBox>
            ) : null}
          </>
        ) : null}
      </div>
      {confirm ? (
        <ConfirmDialog
          open
          title={T.discovery.sweepTitle}
          onClose={() => setConfirm(false)}
          onConfirm={() => void sweep()}
          busy={action.busy}
          error={action.error}
          confirmLabel={T.dc.sweepButton}
        >
          <p>{T.discovery.sweepText}</p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
