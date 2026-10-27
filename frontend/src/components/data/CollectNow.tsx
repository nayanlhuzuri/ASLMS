"use client";

/**
 * Collect Now (design data-collection-redesign, decision 22; round 1): today's manual forms moved here unchanged, each
 * card shown by its own function: One Case (the court search by CNR, case number or party name, with the "already
 * held" and "searched before" warnings before any call, and Fetch Details for found cases; `admin.data_load`), One
 * Day's Cause Lists and Fetch Again (`admin.napix_refetch`, with the warnings before queuing data already held) and
 * the Court Reference Lists (`admin.masters_sync`). Round 3 makes these requests run at once with live progress. The
 * page has no primary: each card's submit is secondary.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Button,
  CheckField,
  DataTable,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  ScrollBox,
  SelectField,
  TabToolbar,
  TextField,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { CaseSearchItem, CourtSearchOut, DataHealth, FetchDetails, HeldCase, QueueState } from "@/lib/api/types";
import { can } from "@/lib/can";
import { DC_KEYS } from "@/lib/dataCollection";
import { formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

export function CollectNow() {
  const me = useMe();
  const oneCase = can(me.data, "admin.data_load");
  const refetch = can(me.data, "admin.napix_refetch");
  const masters = can(me.data, "admin.masters_sync");
  return (
    <div className="stack">
      <TabToolbar />
      <p className={ds.line}>{T.dc.collectIntro}</p>
      {!oneCase && !refetch && !masters ? <EmptyState>{T.dc.collectNothingNote}</EmptyState> : null}
      {oneCase ? (
        <section className={ds.panel} aria-labelledby="dc-one-case">
          <div className="stack">
            <h2 id="dc-one-case">{T.dc.oneCaseTitle}</h2>
            <FetchFromCourt />
          </div>
        </section>
      ) : null}
      {refetch ? <RefetchCards /> : null}
      {masters ? <ReferenceLists /> : null}
    </div>
  );
}

type Pending = { path: string; body: Record<string, unknown>; text: string } | null;

/** The re-fetch forms moved from Health (decision 28), with their warnings before queuing data already held. */
function useQueueAction() {
  const queryClient = useQueryClient();
  const action = useAction();
  const [message, setMessage] = useState<string | null>(null);
  const [warn, setWarn] = useState<Pending>(null);
  async function queue(path: string, body: Record<string, unknown>) {
    setMessage(null);
    setWarn(null);
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
  return { action, message, queue, warning };
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

// ------------------------------------------------------------------------------------------------ One Case (moved unchanged)

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
      await queryClient.invalidateQueries({ queryKey: DC_KEYS.all });
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
            <EmptyState>{T.data.noResults}</EmptyState>
          ) : (
            <ScrollBox label={T.data.results}>
              <DataTable
                caption={T.data.results}
                rows={items}
                rowKey={(it) => it.case.id}
                columns={[
                  {
                    key: "pick",
                    header: <span className="visually-hidden">{T.data.fetchDetails}</span>,
                    label: T.data.fetchDetails,
                    cell: (it) => (
                      <CheckField
                        label={<span className="visually-hidden">{it.case.ref_no}</span>}
                        checked={picked.includes(it.case.ref_no)}
                        onChange={(e) =>
                          setPicked(e.target.checked ? [...picked, it.case.ref_no] : picked.filter((r) => r !== it.case.ref_no))
                        }
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
                  { key: "details", header: T.data.details, cell: (it) => it.dossier_status },
                ]}
              />
            </ScrollBox>
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
