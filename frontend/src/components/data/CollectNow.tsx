"use client";

/**
 * Collect Now (design data-collection-redesign, decisions 22-33; round 3): every manual request, carried out at once by
 * the collector ahead of all other work, with its live progress. Top to bottom: Requests (when one ran in the last 7
 * days), One Case (the court search, then Collect Everything: details and every missing order PDF, the result shown
 * only when everything has run), Several Cases and All Cases Listed on a Day (bulk requests that use the whole
 * allowance, with the "use everything" panel and a confirm), One Day's Cause Lists and Fetch Again, and the Court
 * Reference Lists. Each card shows by its own function; the page has no primary (each card's submit is secondary, the
 * confirming dialog has the primary).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import {
  Button,
  CheckField,
  ConfirmDialog,
  DataTable,
  DefinitionList,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  RadioGroup,
  ScrollBox,
  SelectField,
  TabToolbar,
  TextArea,
  TextField,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { CaseSearchItem, CourtSearchOut, DataHealth, HeldCase, QueueState } from "@/lib/api/types";
import { can } from "@/lib/can";
import {
  DC_KEYS,
  requestWhat,
  type CollectDayCheck,
  type CollectListCheck,
  type CollectOut,
  type CollectSummary,
} from "@/lib/dataCollection";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { COLLECT_ERRORS, T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";
import { todayIst } from "@/lib/workflow";

import { RequestProgress, RequestResult, RequestsCard, UseEverything, useRequest, useRequests } from "./CollectRequests";
import ds from "./data.module.css";

const ONE_MAX = 20;
const LIST_MAX = 200;

export function CollectNow() {
  const me = useMe();
  const oneCase = can(me.data, "admin.data_load");
  const refetch = can(me.data, "admin.napix_refetch");
  const masters = can(me.data, "admin.masters_sync");
  const any = oneCase || refetch || masters;
  const requests = useRequests(any);
  return (
    <div className="stack">
      <TabToolbar updatedAt={requests.dataUpdatedAt || null} />
      <p className={ds.line}>
        {T.dc.collectIntro} {T.dc.collectNowIntro}
      </p>
      {!any ? <EmptyState>{T.dc.collectNothingNote}</EmptyState> : null}
      {any ? <RequestsCard query={requests} /> : null}
      {oneCase ? (
        <section className={ds.panel} aria-labelledby="dc-one-case">
          <div className="stack">
            <h2 id="dc-one-case">{T.dc.oneCaseTitle}</h2>
            <FetchFromCourt />
          </div>
        </section>
      ) : null}
      {oneCase ? <SeveralCases /> : null}
      {oneCase ? <DayCases /> : null}
      {refetch ? <RefetchCards /> : null}
      {masters ? <ReferenceLists /> : null}
    </div>
  );
}

/** A request being watched: its progress until it has finished, then its result (decision 25). */
export function WatchedRequest({ id }: { id: string }) {
  const q = useRequest(id);
  const qc = useQueryClient();
  const finished = !!q.data?.finished;
  useEffect(() => {
    // the Requests card and the figures read again once the request has run
    if (finished) void qc.invalidateQueries({ queryKey: DC_KEYS.requests });
  }, [finished, qc]);
  return (
    <div className="stack" aria-live="polite">
      <ErrorBanner error={q.error} onRetry={() => q.refetch()} messages={COLLECT_ERRORS} />
      {q.isPending ? <Loading lines={2} /> : null}
      {q.data ? (
        <>
          <h3>{q.data.finished ? T.dc.resultTitle : T.dc.collectingTitle}</h3>
          {q.data.finished ? <RequestResult data={q.data} /> : <RequestProgress data={q.data} />}
          {q.data.finished && !q.data.results.length ? <RequestProgress data={q.data} /> : null}
        </>
      ) : null}
    </div>
  );
}

/** The 409 `bulk_running` answer in words: who asked, what and since when (decision 30). */
function bulkRunningText(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.code !== "bulk_running") return null;
  const x = err.extra as Record<string, unknown>;
  const what = requestWhat({
    kind: String(x.kind ?? ""),
    cases: typeof x.cases === "number" ? x.cases : null,
    date: typeof x.date === "string" ? x.date : null,
    ref: null,
    total: 0,
  });
  return T.dc.bulkRunningNote(String(x.asked_by ?? "—"), what, formatDateTime(String(x.asked_at ?? "")));
}

function summaryRunningText(b: CollectSummary): string {
  return T.dc.bulkRunningNote(b.asked_by ?? "—", requestWhat(b), formatDateTime(b.asked_at));
}

/** Sends a collect request; a 409 `bulk_running` becomes a sentence instead of an error. */
function useCollect() {
  const qc = useQueryClient();
  const action = useAction();
  const [watch, setWatch] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  async function send(body: Record<string, unknown>): Promise<boolean> {
    setRunning(null);
    const out = await action.run(() =>
      api<CollectOut>("/admin/data-load/collect", { method: "POST", body }).catch((err) => {
        const text = bulkRunningText(err);
        if (text) {
          setRunning(text);
          return null;
        }
        throw err;
      }),
    );
    if (out.ok && out.value) {
      setWatch(out.value.request_id);
      await qc.invalidateQueries({ queryKey: DC_KEYS.all });
      return true;
    }
    return false;
  }
  return { action, watch, running, send, setWatch };
}

// ------------------------------------------------------------------------------------------------ One Case

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

/**
 * Decision 25, One Case: step 1 searches the court as today (by CNR, case number or party name, with the warnings
 * before any call); step 2, Collect Everything, asks for each ticked case's details and every order PDF it lacks.
 * A CNR search with one result collects by itself. The result shows only when everything has run.
 */
export function FetchFromCourt() {
  const queryClient = useQueryClient();
  const action = useAction();
  const collect = useCollect();
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

  async function send(force: boolean) {
    setWarning(null);
    collect.setWatch(null);
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
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
      const items = out.value.items;
      if (form.kind === "cnr" && items.length === 1 && items[0]) {
        // a CNR search with one result starts by itself (decision 25)
        await collect.send({ kind: "cases", refs: [items[0].case.ref_no] });
      }
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send(false);
  }

  function toggle(ref: string, on: boolean) {
    if (on && picked.length >= ONE_MAX) return;
    setPicked(on ? [...picked, ref] : picked.filter((r) => r !== ref));
  }

  const items: CaseSearchItem[] = result?.items ?? [];
  return (
    <div className="stack">
      <form className="stack" onSubmit={submit} aria-label={T.dc.oneCaseTitle}>
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
          <Button type="submit" variant="secondary" busy={action.busy}>
            {T.data.fetchNow}
          </Button>
        </div>
        <ErrorBanner error={action.error} />
      </form>
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
          <h3>{T.data.results}</h3>
          {items.length === 0 ? (
            <EmptyState>{T.data.noResults}</EmptyState>
          ) : (
            <>
              {items.length > 1 ? <p className="muted">{T.dc.pickHint}</p> : null}
              <ScrollBox label={T.data.results}>
                <DataTable
                  caption={T.data.results}
                  rows={items}
                  rowKey={(it) => it.case.id}
                  columns={[
                    {
                      key: "pick",
                      header: <span className="visually-hidden">{T.dc.collectEverythingButton}</span>,
                      label: T.dc.collectEverythingButton,
                      cell: (it) => (
                        <CheckField
                          label={<span className="visually-hidden">{it.case.ref_no}</span>}
                          checked={picked.includes(it.case.ref_no)}
                          disabled={!picked.includes(it.case.ref_no) && picked.length >= ONE_MAX}
                          onChange={(e) => toggle(it.case.ref_no, e.target.checked)}
                        />
                      ),
                    },
                    {
                      key: "case",
                      header: T.data.case,
                      primary: true,
                      cell: (it) => (
                        <>
                          <span className="mono">{it.case.case_no_text ?? it.case.ref_no}</span>{" "}
                          {!it.visible ? <span className="muted">({T.data.notVisible})</span> : null}
                        </>
                      ),
                    },
                    { key: "cnr", header: T.data.cnr, cell: (it) => <span className="mono">{it.case.cnr ?? "—"}</span> },
                    {
                      key: "details",
                      header: T.dc.detailsCol,
                      cell: (it) =>
                        it.dossier_fetched_at ? T.dc.detailsHeld(formatDate(it.dossier_fetched_at)) : T.dc.detailsNotYet,
                    },
                  ]}
                />
              </ScrollBox>
              {picked.length >= ONE_MAX ? <p className="muted">{T.dc.tooManyNote}</p> : null}
              <div>
                <Button
                  variant="secondary"
                  busy={collect.action.busy}
                  disabled={picked.length === 0}
                  onClick={() => void collect.send({ kind: "cases", refs: picked })}
                >
                  {T.dc.collectEverythingButton}
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}
      <ErrorBanner error={collect.action.error} messages={COLLECT_ERRORS} />
      {collect.watch ? <WatchedRequest id={collect.watch} /> : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ Several Cases

function linesOf(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
}

/** Decision 26: a pasted list of up to 200 cases, checked first (nothing written), then collected at once. */
function SeveralCases() {
  const check = useAction();
  const collect = useCollect();
  const [text, setText] = useState("");
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<CollectListCheck | null>(null);
  const [confirm, setConfirm] = useState(false);
  const lines = linesOf(text);

  async function runCheck(e: FormEvent) {
    e.preventDefault();
    collect.setWatch(null);
    const out = await check.run(() =>
      api<CollectListCheck>("/admin/data-load/collect/list/check", { method: "POST", body: { lines, force } }),
    );
    if (out.ok) setResult(out.value);
  }

  async function send() {
    const ok = await collect.send({ kind: "list", lines, force });
    setConfirm(false);
    if (ok) setResult(null);
  }

  return (
    <section className={ds.panel} aria-labelledby="dc-several">
      <div className="stack">
        <h2 id="dc-several">{T.dc.severalTitle}</h2>
        <form className="stack" aria-label={T.dc.severalTitle} onSubmit={runCheck}>
          <TextArea
            label={T.dc.linesLabel}
            hint={T.dc.linesHint}
            rows={6}
            required
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setResult(null);
            }}
          />
          <CheckField
            label={T.dc.forceLabel}
            checked={force}
            onChange={(e) => {
              setForce(e.target.checked);
              setResult(null);
            }}
          />
          {lines.length > LIST_MAX ? <p className="muted">{COLLECT_ERRORS.too_many!({ limit: LIST_MAX })}</p> : null}
          <div>
            <Button type="submit" variant="secondary" busy={check.busy} disabled={!lines.length}>
              {T.dc.checkListButton}
            </Button>
          </div>
        </form>
        <ErrorBanner error={check.error ?? collect.action.error} messages={COLLECT_ERRORS} />
        {collect.running ? <Notice tone="warning">{collect.running}</Notice> : null}
        {result ? (
          <div className="stack">
            <ScrollBox label={T.dc.severalTitle}>
              <DataTable
                caption={T.dc.severalTitle}
                rows={result.items}
                rowKey={(i) => i.line}
                columns={[
                  { key: "line", header: T.dc.lineCols.line, primary: true, cell: (i) => <span className="mono">{i.line}</span> },
                  {
                    key: "state",
                    header: T.dc.lineCols.state,
                    cell: (i) => (
                      <>
                        {i.state === "merged" && i.merged_into_ref_no
                          ? T.dc.mergedInto(i.merged_into_ref_no)
                          : (T.dc.lineStates[i.state] ?? i.state)}
                        {i.state === "not_held" ? (
                          <>
                            <br />
                            <span className="muted">{T.dc.notHeldHint}</span>
                          </>
                        ) : null}
                      </>
                    ),
                  },
                  {
                    key: "case",
                    header: T.dc.lineCols.case,
                    cell: (i) =>
                      i.case ? (
                        <span className="mono">{i.case.case_no_text ?? i.case.ref_no}</span>
                      ) : i.state === "will_fetch" ? (
                        T.dc.newFromCourt
                      ) : (
                        "—"
                      ),
                  },
                  {
                    key: "details",
                    header: T.dc.lineCols.details,
                    cell: (i) => (i.details_fetched_at ? T.dc.detailsHeld(formatDate(i.details_fetched_at)) : "—"),
                  },
                ]}
              />
            </ScrollBox>
            <p>{T.dc.toFetchNote(result.to_fetch)}</p>
            {result.to_fetch > 0 ? (
              <>
                <UseEverything plan={result.plan} />
                {result.bulk ? <Notice tone="warning">{summaryRunningText(result.bulk)}</Notice> : null}
                <div>
                  <Button variant="secondary" disabled={!!result.bulk} onClick={() => setConfirm(true)}>
                    {T.dc.collectEverythingButton}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
        {collect.watch ? <WatchedRequest id={collect.watch} /> : null}
      </div>
      <ConfirmDialog
        open={confirm}
        title={T.dc.confirmCollectTitle}
        onClose={() => setConfirm(false)}
        onConfirm={() => void send()}
        busy={collect.action.busy}
        confirmLabel={T.dc.confirmCollectButton}
      >
        {result ? (
          <div className="stack">
            <p>{T.dc.toFetchNote(result.to_fetch)}</p>
            <UseEverything plan={result.plan} />
          </div>
        ) : null}
      </ConfirmDialog>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ a day

function tomorrowIst(): string {
  return todayIst(new Date(Date.now() + 24 * 3600 * 1000));
}

/** Decision 27: every case on a day's current lists (never fetched, or every case), checked first, then collected. */
function DayCases() {
  const check = useAction();
  const collect = useCollect();
  const [date, setDate] = useState("");
  const [scope, setScope] = useState<"never" | "all">("never");
  const [result, setResult] = useState<CollectDayCheck | null>(null);
  const [confirm, setConfirm] = useState(false);

  async function runCheck(e: FormEvent) {
    e.preventDefault();
    collect.setWatch(null);
    const out = await check.run(() =>
      api<CollectDayCheck>(`/admin/data-load/collect/day?date=${encodeURIComponent(date)}&scope=${scope}`),
    );
    if (out.ok) setResult(out.value);
  }

  async function send() {
    const ok = await collect.send({ kind: "day", date, scope });
    setConfirm(false);
    if (ok) setResult(null);
  }

  const f = T.dc.dayFacts;
  return (
    <section className={ds.panel} aria-labelledby="dc-day">
      <div className="stack">
        <h2 id="dc-day">{T.dc.dayTitle}</h2>
        <form className="stack" aria-label={T.dc.dayTitle} onSubmit={runCheck}>
          <div className={ds.fieldRow}>
            <TextField
              label={T.data.date}
              type="date"
              required
              max={tomorrowIst()}
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setResult(null);
              }}
            />
          </div>
          <RadioGroup
            legend={T.dc.whichLabel}
            name="dc-day-scope"
            value={scope}
            onChange={(v) => {
              setScope(v as "never" | "all");
              setResult(null);
            }}
            options={[
              { value: "never", label: T.dc.scopeOptions.never! },
              { value: "all", label: T.dc.scopeOptions.all!, hint: T.dc.scopeAllHint },
            ]}
          />
          <div>
            <Button type="submit" variant="secondary" busy={check.busy} disabled={!date}>
              {T.dc.checkDayButton}
            </Button>
          </div>
        </form>
        <ErrorBanner error={check.error ?? collect.action.error} messages={COLLECT_ERRORS} />
        {collect.running ? <Notice tone="warning">{collect.running}</Notice> : null}
        {result ? (
          <div className="stack">
            <DefinitionList
              items={[
                [f.lists, formatNumber(result.lists)],
                [f.listed, formatNumber(result.cases_listed)],
                [
                  f.withDetails,
                  result.details_from && result.details_to
                    ? `${formatNumber(result.with_details)} (${T.dc.detailsBetween(formatDate(result.details_from), formatDate(result.details_to))})`
                    : formatNumber(result.with_details),
                ],
                [f.never, formatNumber(result.never_fetched)],
                [f.recent, formatNumber(result.refreshed_recently)],
                [f.noReference, formatNumber(result.no_reference)],
                [f.toFetch, <b key="to">{formatNumber(result.to_fetch)}</b>],
              ]}
            />
            {result.to_fetch === 0 ? (
              <Notice>{T.dc.dayNothingNote}</Notice>
            ) : (
              <>
                <UseEverything plan={result.plan} />
                {result.bulk ? <Notice tone="warning">{summaryRunningText(result.bulk)}</Notice> : null}
                <div>
                  <Button variant="secondary" disabled={!!result.bulk} onClick={() => setConfirm(true)}>
                    {T.dc.collectEverythingButton}
                  </Button>
                </div>
              </>
            )}
          </div>
        ) : null}
        {collect.watch ? <WatchedRequest id={collect.watch} /> : null}
      </div>
      <ConfirmDialog
        open={confirm}
        title={T.dc.confirmCollectTitle}
        onClose={() => setConfirm(false)}
        onConfirm={() => void send()}
        busy={collect.action.busy}
        confirmLabel={T.dc.confirmCollectButton}
      >
        {result ? (
          <div className="stack">
            <p>{T.dc.toFetchNote(result.to_fetch)}</p>
            <UseEverything plan={result.plan} />
          </div>
        ) : null}
      </ConfirmDialog>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ the existing buttons

type Pending = { path: string; body: Record<string, unknown>; text: string } | null;

/** The re-fetch forms (decision 28), with their warnings before queuing data already held; carried out at once. */
function useQueueAction() {
  const queryClient = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const [warn, setWarn] = useState<Pending>(null);
  const [watch, setWatch] = useState<string | null>(null);
  async function queue(path: string, body: Record<string, unknown>) {
    setMessage(null);
    setWarn(null);
    setWatch(null);
    const out = await action.run(() =>
      api<QueueState>(path, { method: "POST", body }).catch((err) => {
        if (err instanceof ApiError && err.status === 409 && err.code === "already_held") {
          const text = path.endsWith("/day")
            ? T.data.dayHeld(String(err.extra.status ?? ""), Number(err.extra.lists_stored ?? 0))
            : T.data.caseHeld(formatDateTime(String(err.extra.dossier_fetched_at ?? "")));
          setWarn({ path, body, text });
          return null;
        }
        throw err;
      }),
    );
    if (out.ok && out.value) {
      setMessage(T.data.queued(T.dc.kinds[out.value.kind] ?? out.value.kind, out.value.status ?? "—"));
      if (out.value.request_id) setWatch(out.value.request_id);
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
      await queryClient.invalidateQueries({ queryKey: ["data-health"] });
    }
  }
  const warning = (
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
  );
  const progress = watch ? <WatchedRequest id={watch} /> : null;
  return { action, message, queue, warning, progress };
}

function RefetchCards() {
  const day = useQueueAction();
  const again = useQueueAction();
  const [date, setDate] = useState("");
  const [caseRef, setCaseRef] = useState("");
  const [orderCase, setOrderCase] = useState({ case: "", order_id: "" });
  return (
    <>
      <section className={ds.panel} aria-labelledby="dc-one-day">
        <div className="stack">
          <h2 id="dc-one-day">{T.dc.oneDayTitle}</h2>
          <ErrorBanner error={day.action.error} />
          {day.message ? <Notice>{day.message}</Notice> : null}
          <form
            className="row"
            aria-label={T.data.refetchDay}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void day.queue("/admin/napix/refetch/day", { date });
            }}
          >
            <TextField label={T.data.date} type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
            <Button type="submit" variant="secondary" busy={day.action.busy}>
              {T.data.refetchDay}
            </Button>
          </form>
          {day.warning}
          {day.progress}
        </div>
      </section>
      <section className={ds.panel} aria-labelledby="dc-fetch-again">
        <div className="stack">
          <h2 id="dc-fetch-again">{T.dc.fetchAgainTitle}</h2>
          <ErrorBanner error={again.action.error} />
          {again.message ? <Notice>{again.message}</Notice> : null}
          <form
            className="row"
            aria-label={T.data.refetchCase}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void again.queue("/admin/napix/refetch/case", { case: caseRef.trim() });
            }}
          >
            <TextField label={T.data.caseRef} required value={caseRef} onChange={(e) => setCaseRef(e.target.value)} />
            <Button type="submit" variant="secondary" busy={again.action.busy}>
              {T.data.refetchCase}
            </Button>
          </form>
          <form
            className="row"
            aria-label={T.data.refetchOrder}
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void again.queue("/admin/napix/refetch/order", { case: orderCase.case.trim(), order_id: orderCase.order_id.trim() });
            }}
          >
            <TextField
              label={T.data.caseRef}
              required
              value={orderCase.case}
              onChange={(e) => setOrderCase({ ...orderCase, case: e.target.value })}
            />
            <TextField
              label={T.data.orderId}
              required
              value={orderCase.order_id}
              onChange={(e) => setOrderCase({ ...orderCase, order_id: e.target.value })}
            />
            <Button type="submit" variant="secondary" busy={again.action.busy}>
              {T.data.refetchOrder}
            </Button>
          </form>
          {again.warning}
          {again.progress}
        </div>
      </section>
    </>
  );
}

/** Decision 29: Update Now and each reference list's last update and rows. */
function ReferenceLists() {
  const sync = useQueueAction();
  const health = useQuery({ queryKey: ["data-health"], queryFn: () => api<DataHealth>("/admin/data-health") });
  return (
    <section className={ds.panel} aria-labelledby="dc-reference">
      <div className="stack">
        <div className={ds.panelHead}>
          <h2 id="dc-reference">{T.dc.referenceTitle}</h2>
          <Button variant="secondary" busy={sync.action.busy} onClick={() => void sync.queue("/admin/napix/sync-masters", {})}>
            {T.dc.updateNow}
          </Button>
        </div>
        <ErrorBanner error={sync.action.error ?? health.error} />
        {sync.message ? <Notice>{sync.message}</Notice> : null}
        {sync.progress}
        {health.isPending ? <Loading /> : null}
        {health.data ? (
          <DataTable
            caption={T.dc.referenceTitle}
            rows={health.data.masters}
            rowKey={(m) => m.master}
            columns={[
              { key: "master", header: T.dc.cols.kind, primary: true, cell: (m) => T.dc.masters[m.master] ?? m.master },
              { key: "at", header: T.dc.cols.lastRun, cell: (m) => formatDateTime(m.fetched_at) },
              { key: "rows", header: T.dc.cols.total, align: "right", cell: (m) => T.dc.masterRows(formatNumber(m.row_count)) },
            ]}
            empty={<EmptyState>{T.dc.neverUpdated}</EmptyState>}
          />
        ) : null}
      </div>
    </section>
  );
}
