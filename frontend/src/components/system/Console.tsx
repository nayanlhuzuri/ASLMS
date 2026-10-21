"use client";

/**
 * The request console of one court API (design system-health-inspector, decisions 1-9, 12 and 14): a large modal at
 * `?api=<key>&tab=…` with the tabs Request (the pre-filled, editable form and the full request built by the server
 * from the code that sends it), Response (this send or the last one: statuses with their meanings, timing, rate-limit
 * headers, the signature check, the structure against the field inventory and, for State-wide viewers, the full
 * answer), History (row 109's panel content) and Documentation. Opening it never calls the court: the console and the
 * preview are reads. "Send · 1 court call" is the modal's only primary button and posts once. No secret ever reaches
 * the browser: the server sends the masked envelope and templates with placeholders.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import {
  Badge,
  Button,
  CodeBlock,
  Collapsible,
  CopyButton,
  DataTable,
  ErrorBanner,
  KvList,
  Loading,
  Modal,
  Notice,
  StatusDot,
  TextField,
  buttonClass,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api/client";
import type {
  AnswerStructure,
  ApiCard,
  ApiConsole,
  ApiTest,
  ConsoleRequest,
  InventoryDiff,
  LastSend,
  NapixReference,
  StoredResponse,
} from "@/lib/api/types";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { CONSOLE_ERRORS, errorText, T } from "@/lib/messages";
import { sendBlock, signatureWord, toneOf } from "@/lib/systemHealth";

import { ApiHistory } from "./ApiPanel";
import s from "./system.module.css";

export const CONSOLE_TABS = ["request", "response", "history", "docs"] as const;
export type ConsoleTab = (typeof CONSOLE_TABS)[number];
export const PREVIEW_DELAY_MS = 400;
const C = T.system.console;

export function docHref(doc: string, page: number): string {
  return `/api/backend/admin/system-health/docs/${doc}#page=${page}`;
}

/** The `?` help button: opens the NAPIX document at a page in a new tab (the browser's viewer honours `#page=`). */
export function HelpLink({ doc, page, label }: { doc: string; page: number; label: string }) {
  return (
    <a className={buttonClass("ghost", "sm")} href={docHref(doc, page)} target="_blank" rel="noopener noreferrer" aria-label={label} title={label}>
      <span aria-hidden="true">?</span>
    </a>
  );
}

/** Tabs inside a modal: a tablist with arrow keys; only the active panel is drawn (the form's state lives above). */
export function ModalTabs<K extends string>({
  tabs,
  labels,
  active,
  onSelect,
  label,
  idPrefix,
  children,
}: {
  tabs: readonly K[];
  labels: Record<string, string>;
  active: K;
  onSelect: (tab: K) => void;
  label: string;
  idPrefix: string;
  children: ReactNode;
}) {
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = tabs[(index + delta + tabs.length) % tabs.length]!;
    onSelect(next);
    document.getElementById(`${idPrefix}-tab-${next}`)?.focus();
  }
  return (
    <div>
      <div role="tablist" aria-label={label} className={s.tablist}>
        {tabs.map((t, i) => (
          <button
            key={t}
            id={`${idPrefix}-tab-${t}`}
            type="button"
            role="tab"
            className={s.tab}
            aria-selected={active === t}
            aria-controls={`${idPrefix}-panel-${t}`}
            tabIndex={active === t ? 0 : -1}
            onClick={() => onSelect(t)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {labels[t] ?? t}
          </button>
        ))}
      </div>
      <div id={`${idPrefix}-panel-${active}`} role="tabpanel" aria-labelledby={`${idPrefix}-tab-${active}`} className="stack">
        {children}
      </div>
    </div>
  );
}

function download(name: string, text: string) {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

type Values = Record<string, string>;

function valuesOf(console: ApiConsole): Values {
  return Object.fromEntries(console.fields.map((f) => [f.name, f.value]));
}

// ------------------------------------------------------------------------------------------------ the request tab

function RequestView({
  request,
  console,
  values,
  errors,
  typed,
  onChange,
  onReset,
  previewing,
  apiKey,
}: {
  request: ConsoleRequest;
  console: ApiConsole;
  values: Values;
  errors: Record<string, string>;
  typed: Set<string>;
  onChange: (name: string, value: string) => void;
  onReset: () => void;
  previewing: boolean;
  apiKey: string;
}) {
  const exporting = useRef(false);
  const [exportError, setExportError] = useState<unknown>(null);
  async function exportPostman() {
    if (exporting.current) return;
    exporting.current = true;
    setExportError(null);
    try {
      const body = await api<unknown>(`/admin/system-health/napix/${apiKey}/postman`, { method: "POST", body: { values } });
      download(`aslms-napix-${apiKey}.postman_collection.json`, JSON.stringify(body, null, 2));
    } catch (error) {
      setExportError(error);
    } finally {
      exporting.current = false;
    }
  }
  const last = console.last_send;
  return (
    <div className="stack">
      <CodeBlock label={C.methodUrl}>{`${request.method} ${request.url}`}</CodeBlock>
      {request.method_note ? <p className={s.muted}>{request.method_note}</p> : null}
      <section className="stack" aria-label={C.params}>
        <h3>{C.params}</h3>
        {console.sample.available && console.sample.label ? (
          <p className={s.muted}>
            {C.sample}: {console.sample.label}
          </p>
        ) : console.sample.reason && console.fields.length ? (
          <p className={s.muted}>{console.sample.reason}</p>
        ) : null}
        {request.no_input_note ? <p>{request.no_input_note}</p> : null}
        <div className={s.fieldGrid}>
          {console.fields.map((f) => {
            const source = typed.has(f.name) ? "typed" : f.source;
            const hint = [
              `${C.source[source] ?? source} · ${f.mandatory ? C.mandatory : C.optional}`,
              `${f.format}. ${f.meaning}`,
              f.hint,
            ]
              .filter(Boolean)
              .join(" — ");
            return (
              <TextField
                key={f.name}
                label={<span className="cno">{f.name}</span>}
                value={values[f.name] ?? ""}
                onChange={(e) => onChange(f.name, e.target.value)}
                hint={hint}
                error={errors[f.name]}
                autoComplete="off"
                spellCheck={false}
              />
            );
          })}
        </div>
        {console.fields.length && console.sample.available ? (
          <div>
            <Button variant="link" onClick={onReset}>
              {C.reset}
            </Button>
          </div>
        ) : null}
      </section>
      <CodeBlock label={C.plain}>{request.plain}</CodeBlock>
      {previewing ? (
        <p className={s.muted} role="status">
          <StatusDot tone="busy" pulse /> {C.checking}
        </p>
      ) : null}
      <section className="stack" aria-label={C.envelope}>
        <h3>{C.envelope}</h3>
        <DataTable
          caption={C.envelope}
          rows={request.envelope}
          rowKey={(r) => r.name}
          columns={[
            { key: "name", header: T.system.docs.name, cell: (r) => <span className="cno">{r.name}</span>, primary: true },
            { key: "shown", header: T.system.docs.meaning, cell: (r) => <span className={s.mono}>{r.shown}</span> },
            { key: "note", header: T.system.docs.note, cell: (r) => r.note },
          ]}
        />
      </section>
      <section className="stack" aria-label={C.headers}>
        <h3>{C.headers}</h3>
        <KvList items={request.headers.map((h) => [h.name, <span key={h.name} className={s.mono}>{h.shown}</span>])} />
      </section>
      {last?.params_sha256 ? <p>{C.sameAsLast(last.params_sha256 === request.plain_sha256)}</p> : null}
      <section className="stack" aria-label={C.templates}>
        <h3>{C.templates}</h3>
        <p className={s.muted}>{request.templates.note}</p>
        <CodeBlock label={C.curl}>{request.templates.curl}</CodeBlock>
        <div>
          <Button variant="secondary" onClick={() => void exportPostman()}>
            {C.postman}
          </Button>
        </div>
        <ErrorBanner error={exportError} messages={CONSOLE_ERRORS} />
      </section>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ the response tab

interface SendView {
  at: string;
  by: string;
  recorded: boolean;
  edited: boolean | null | undefined;
  status: string;
  reason: string;
  attempts: number;
  method: string;
  url: string;
  plain: string | null | undefined;
  http_status: number | null | undefined;
  http_meaning: string | null | undefined;
  napix_status: number | null | undefined;
  napix_meaning: string | null | undefined;
  error_family: string | null | undefined;
  duration_ms: number;
  rate_limit: { limit?: number | null; remaining?: number | null } | null | undefined;
  window_reset_at: string | null | undefined;
  token_verified: boolean | null | undefined;
  summary: ApiTest["summary"] | null | undefined;
  structure: AnswerStructure | null | undefined;
  inventory_diff: InventoryDiff | null | undefined;
  response_id: string | null | undefined;
}

function fromTest(r: ApiTest, resetAt: string | null | undefined): SendView {
  return {
    at: r.called_at,
    by: C.yourSend,
    recorded: true,
    edited: r.edited,
    status: r.status,
    reason: r.reason,
    attempts: r.attempts,
    method: r.request.method,
    url: r.request.url,
    plain: r.request.plain,
    http_status: r.http_status,
    http_meaning: r.http_meaning,
    napix_status: r.napix_status,
    napix_meaning: r.napix_meaning,
    error_family: r.error_family,
    duration_ms: r.duration_ms,
    rate_limit: r.rate_limit,
    window_reset_at: resetAt,
    token_verified: r.token_verified,
    summary: r.summary,
    structure: r.structure,
    inventory_diff: r.inventory_diff,
    response_id: r.response_id,
  };
}

function fromLast(l: LastSend): SendView {
  return { ...l, by: l.by === "you" ? C.yourSend : C.aPerson, response_id: l.response_id };
}

export function StructureOutline({ structure }: { structure: AnswerStructure }) {
  return (
    <section className="stack" aria-label={C.structure}>
      <h3>{C.structure}</h3>
      <p className={s.muted}>{C.structureNote}</p>
      <ul className={s.outline}>
        {structure.paths.map((p) => (
          <li key={p.path} style={{ paddingLeft: `${Math.min(6, p.path.split(/\.|\[\]/).length - 1) * 12}px` }}>
            <span className="cno">{p.path}</span> <span className={s.muted}>{p.type}</span> <span className={s.muted}>× {formatNumber(p.count)}</span>
          </li>
        ))}
      </ul>
      {structure.more > 0 ? <p className={s.muted}>{C.more(structure.more)}</p> : null}
    </section>
  );
}

export function InventoryNotice({ diff }: { diff: InventoryDiff }) {
  if (!diff.checked) return null;
  return (
    <>
      {diff.new.length ? (
        <Notice tone="warning">
          <b>{C.newPaths}</b> {C.newPathsNote}
          <ul className={s.outline}>
            {diff.new.map((p) => (
              <li key={p} className="cno">
                {p}
              </li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {diff.absent.length ? (
        <Collapsible summary={C.absentPaths(diff.absent.length)}>
          <ul className={s.outline}>
            {diff.absent.map((p) => (
              <li key={p} className="cno">
                {p}
              </li>
            ))}
          </ul>
        </Collapsible>
      ) : null}
    </>
  );
}

/** The full decrypted answer: fetched when the section is first expanded (each opening is audited by the server). */
function FullAnswerBody({ apiKey, source, responseId }: { apiKey: string; source: "send" | "latest"; responseId?: string | null }) {
  const qs = source === "send" ? `source=send&response_id=${responseId ?? ""}` : "source=latest";
  const raw = useQuery({
    queryKey: ["system-health", "raw", apiKey, source, responseId ?? null],
    queryFn: () => api<StoredResponse>(`/admin/system-health/napix/${apiKey}/response?${qs}`),
    staleTime: Infinity,
  });
  if (raw.error) return <ErrorBanner error={raw.error} messages={CONSOLE_ERRORS} />;
  if (!raw.data) return <Loading lines={2} />;
  const text = JSON.stringify(raw.data.payload, null, 2);
  return (
    <div className="stack">
      <p className={s.muted}>{C.fullAnswerAudited}</p>
      <div className={s.rowGap}>
        <CopyButton text={text} />
        <Button variant="ghost" size="sm" onClick={() => download(`aslms-napix-${apiKey}-answer.json`, text)}>
          {C.download}
        </Button>
      </div>
      <pre className={s.raw} tabIndex={0} aria-label={C.fullAnswer}>
        {text}
      </pre>
    </div>
  );
}

function FullAnswer({
  apiKey,
  allowed,
  note,
  source,
  responseId,
}: {
  apiKey: string;
  allowed: boolean;
  note: string | null | undefined;
  source: "send" | "latest";
  responseId?: string | null;
}) {
  return (
    <Collapsible summary={C.fullAnswer}>
      {allowed ? <FullAnswerBody apiKey={apiKey} source={source} responseId={responseId} /> : <p>{note}</p>}
    </Collapsible>
  );
}

function ResponseView({
  apiKey,
  console,
  result,
}: {
  apiKey: string;
  console: ApiConsole;
  result: ApiTest | null;
}) {
  const view = result ? fromTest(result, console.last_send?.window_reset_at) : console.last_send ? fromLast(console.last_send) : null;
  const latest = console.latest_answer;
  if (!view) {
    if (!latest) return <p className={s.muted}>{C.noSend}</p>;
    return (
      <div className="stack">
        <p className={s.muted}>{C.latest(formatDateTime(latest.at), T.system.by[latest.by]?.toLowerCase() ?? latest.by)}</p>
        {latest.structure ? <StructureOutline structure={latest.structure} /> : null}
        {latest.inventory_diff ? <InventoryNotice diff={latest.inventory_diff} /> : null}
        {latest.response_available ? (
          <FullAnswer apiKey={apiKey} allowed={console.full_answer_allowed} note={console.full_answer_note} source="latest" />
        ) : null}
        <p className={s.muted}>{console.not_saved_note}</p>
      </div>
    );
  }
  const nr = C.notRecorded;
  const rate = view.rate_limit
    ? view.rate_limit.limit == null && view.rate_limit.remaining == null
      ? C.noRate
      : C.rateValue(String(view.rate_limit.limit ?? "—"), String(view.rate_limit.remaining ?? "—"))
    : view.recorded
      ? C.noRate
      : nr;
  const pdf = view.summary?.kind === "pdf";
  const items: [ReactNode, ReactNode][] = [
    [C.when, formatDateTime(view.at)],
    [C.by, view.by],
    [C.values, view.edited == null ? nr : view.edited ? C.edited : C.held],
    [C.attempts, String(view.attempts)],
    [C.httpStatus, view.http_status == null ? "—" : `${view.http_status} — ${view.http_meaning ?? ""}`],
    [C.napixStatus, view.napix_status == null ? "—" : `${view.napix_status} — ${view.napix_meaning ?? ""}`],
    [C.family, view.error_family ?? "—"],
    [C.reason, view.reason],
    [C.duration, C.durationMs(formatNumber(view.duration_ms))],
    [C.rate, view.window_reset_at ? `${rate} · ${C.resets(formatTime(view.window_reset_at))}` : rate],
    [C.signature, view.recorded ? signatureWord(view.token_verified) : nr],
  ];
  return (
    <div className="stack" aria-live="polite">
      <p className={s.outcome}>
        <Badge tone={toneOf(view.status)}>{C.outcome[view.status] ?? view.status}</Badge>
      </p>
      <KvList items={items} />
      <section className="stack" aria-label={C.requestSent}>
        <h3>{C.requestSent}</h3>
        <CodeBlock label={C.methodUrl}>{`${view.method} ${view.url}`}</CodeBlock>
        {view.plain != null ? <CodeBlock label={C.plain}>{view.plain}</CodeBlock> : <p className={s.muted}>{nr}</p>}
      </section>
      {view.summary && view.summary.facts.length ? (
        <section className="stack" aria-label={C.summary}>
          <h3>{C.summary}</h3>
          {pdf ? <p>{C.pdf(view.summary.facts.map((f) => `${f.label} ${f.value}`).join(", "))}</p> : null}
          <KvList items={view.summary.facts.map((f) => [f.label, f.value])} />
        </section>
      ) : null}
      {view.structure ? <StructureOutline structure={view.structure} /> : null}
      {view.inventory_diff ? <InventoryNotice diff={view.inventory_diff} /> : null}
      {view.response_id ? (
        <FullAnswer
          key={view.response_id}
          apiKey={apiKey}
          allowed={console.full_answer_allowed}
          note={console.full_answer_note}
          source="send"
          responseId={view.response_id}
        />
      ) : null}
      <p className={s.muted}>{console.not_saved_note}</p>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ documentation

export function DocsView({ apiKey }: { apiKey: string }) {
  const ref = useQuery({
    queryKey: ["system-health", "reference", apiKey],
    queryFn: () => api<NapixReference>(`/admin/system-health/napix/${apiKey}/reference`),
    staleTime: Infinity,
  });
  const D = T.system.docs;
  if (ref.error) return <ErrorBanner error={ref.error} onRetry={() => void ref.refetch()} />;
  if (!ref.data) return <Loading lines={3} />;
  const r = ref.data;
  return (
    <div className="stack">
      {r.doc.available ? (
        <p>
          <a href={docHref(r.doc.doc, r.doc.page)} target="_blank" rel="noopener noreferrer">
            {D.openAt(r.doc.section, r.doc.page)}
          </a>
        </p>
      ) : (
        <Notice tone="warning">{D.missing}</Notice>
      )}
      <section className="stack" aria-label={D.inputs}>
        <h3>{D.inputs}</h3>
        {r.inputs.length ? (
          <DataTable
            caption={D.inputs}
            rows={r.inputs}
            rowKey={(i) => i.name}
            columns={[
              { key: "name", header: D.name, cell: (i) => <span className="cno">{i.name}</span>, primary: true },
              { key: "need", header: D.need, cell: (i) => (i.mandatory ? C.mandatory : C.optional) },
              { key: "format", header: D.format, cell: (i) => i.format },
              { key: "meaning", header: D.meaning, cell: (i) => i.meaning },
              { key: "note", header: D.note, cell: (i) => i.note ?? "—" },
            ]}
          />
        ) : (
          <p className={s.muted}>{D.noInputs}</p>
        )}
      </section>
      <section className="stack" aria-label={D.outputs}>
        <h3>{D.outputs}</h3>
        {r.outputs.note ? <p>{r.outputs.note}</p> : null}
        {r.outputs.paths.length ? (
          <Collapsible summary={`${D.outputs} (${r.outputs.paths.length})`}>
            <ul className={s.outline}>
              {r.outputs.paths.map((p) => (
                <li key={p.path}>
                  <span className="cno">{p.path}</span> <span className={s.muted}>{p.type}</span>
                </li>
              ))}
            </ul>
          </Collapsible>
        ) : null}
      </section>
      <section className="stack" aria-label={D.statuses}>
        <h3>{D.statuses}</h3>
        <DataTable
          caption={D.statuses}
          rows={r.statuses}
          rowKey={(x) => x.code}
          columns={[
            { key: "code", header: D.code, cell: (x) => <span className="cno">{x.code}</span>, primary: true },
            { key: "name", header: D.name, cell: (x) => x.name ?? "—" },
            { key: "meaning", header: D.meaning, cell: (x) => (x.listed ? `${x.meaning} (${D.listed})` : x.meaning) },
          ]}
        />
      </section>
      <section className="stack" aria-label={D.build}>
        <h3>{D.build}</h3>
        <ol className={s.steps}>
          {r.build_steps.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ol>
      </section>
      {r.read_steps.length ? (
        <section className="stack" aria-label={D.read}>
          <h3>{D.read}</h3>
          <ol className={s.steps}>
            {r.read_steps.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ol>
        </section>
      ) : null}
      {r.doc.available ? (
        <section className="stack" aria-label={D.links}>
          <h3>{D.links}</h3>
          <ul className={s.steps}>
            {r.general_links.map((l) => (
              <li key={`${l.doc}-${l.page}-${l.label}`}>
                <a href={docHref(l.doc, l.page)} target="_blank" rel="noopener noreferrer">
                  {D.openAt(l.label, l.page)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ the console

export function ConsoleModal({
  apiKey,
  card,
  napixEnabled,
  tab,
  onTab,
  onClose,
  onSent,
}: {
  apiKey: string;
  card: ApiCard;
  napixEnabled: boolean;
  tab: ConsoleTab;
  onTab: (tab: ConsoleTab) => void;
  onClose: () => void;
  onSent: () => void;
}) {
  const qc = useQueryClient();
  const key = ["system-health", "console", apiKey] as const;
  const consoleQuery = useQuery({ queryKey: key, queryFn: () => api<ApiConsole>(`/admin/system-health/napix/${apiKey}/console`) });
  const data = consoleQuery.data;
  // the form's values: the console's pre-filled ones until the person edits (Reset goes back to them)
  const [edits, setEdits] = useState<Values | null>(null);
  const values: Values | null = edits ?? (data ? valuesOf(data) : null);
  const [typed, setTyped] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [request, setRequest] = useState<ConsoleRequest | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [result, setResult] = useState<ApiTest | null>(null);
  const [sendError, setSendError] = useState<unknown>(null);
  const [sending, setSending] = useState(false);
  const inFlight = useRef(false);
  const [now, setNow] = useState(() => Date.now());

  // the request is rebuilt by the server 400 ms after typing stops (no call)
  useEffect(() => {
    if (!dirty || values === null) return;
    let live = true;
    const timer = setTimeout(() => {
      api<ConsoleRequest>(`/admin/system-health/napix/${apiKey}/preview`, { method: "POST", body: { values } })
        .then((next) => {
          if (!live) return;
          setRequest(next);
          setErrors({});
        })
        .catch((error: unknown) => {
          if (!live) return;
          const fields = error instanceof ApiError ? (error.extra.errors as Record<string, string> | undefined) : undefined;
          setErrors(fields ?? {});
          if (!fields) setSendError(error);
        })
        .finally(() => live && setPreviewing(false));
    }, PREVIEW_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [dirty, values, apiKey]);

  // the wait for the next allowed send counts down
  const nextAt = data?.send.next_allowed_at;
  useEffect(() => {
    if (!nextAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [nextAt]);

  function change(name: string, value: string) {
    setEdits({ ...(values ?? {}), [name]: value });
    setPreviewing(true);
    setTyped((t) => new Set([...t, name]));
    setDirty((n) => n + 1);
  }
  function reset() {
    if (!data) return;
    setEdits(null);
    setTyped(new Set());
    setErrors({});
    setRequest(null);
  }

  async function send() {
    if (inFlight.current || !values) return; // a double click sends one request
    inFlight.current = true;
    setSending(true);
    setSendError(null);
    try {
      const out = await api<ApiTest>(`/admin/system-health/napix/${apiKey}/test`, { method: "POST", body: { values } });
      setResult(out);
      onTab("response");
      onSent();
    } catch (error) {
      setSendError(error);
      const fields = error instanceof ApiError ? (error.extra.errors as Record<string, string> | undefined) : undefined;
      if (fields) setErrors(fields);
    } finally {
      inFlight.current = false;
      setSending(false);
      void qc.invalidateQueries({ queryKey: key });
    }
  }

  const name = T.system.apis[card.key] ?? card.label;
  const shown: ConsoleRequest | null = request ?? data ?? null;
  const empty = data ? data.fields.some((f) => !(values?.[f.name] ?? "").trim()) : true;
  const block = data
    ? sendBlock(data.send, napixEnabled, now) ??
      (empty ? C.typeFirst : Object.keys(errors).length ? C.fixFirst : previewing ? C.checking : null)
    : T.loading;
  const reasonId = `send-reason-${apiKey}`;
  const footer = (
    <div className={s.footer}>
      {block ? (
        <span id={reasonId} className={s.reason}>
          {block}
        </span>
      ) : null}
      <Button busy={sending} disabled={!!block} aria-describedby={block ? reasonId : undefined} onClick={() => void send()}>
        {C.send}
      </Button>
    </div>
  );
  const header = data ? (
    <div className={s.modalHeader}>
      <span className={s.muted}>{`${data.method} ${data.url}`}</span>
      <HelpLink doc={data.doc.doc} page={data.doc.page} label={C.help} />
    </div>
  ) : null;

  return (
    <Modal open title={name} onClose={onClose} header={header} footer={footer}>
      <ErrorBanner error={consoleQuery.error} onRetry={() => void consoleQuery.refetch()} />
      {consoleQuery.isPending ? <Loading lines={4} /> : null}
      {data && shown ? (
        <ModalTabs tabs={CONSOLE_TABS} labels={C.tabs} active={tab} onSelect={onTab} label={C.tabsLabel} idPrefix={`console-${apiKey}`}>
          {sending ? (
            <p className={s.testing} role="status">
              <StatusDot tone="busy" pulse /> {C.sending}
            </p>
          ) : null}
          {sendError ? (
            <p className={s.error} role="alert">
              {errorText(sendError, CONSOLE_ERRORS)}
            </p>
          ) : null}
          {tab === "request" && values ? (
            <RequestView
              request={shown}
              console={data}
              values={values}
              errors={errors}
              typed={typed}
              onChange={change}
              onReset={reset}
              previewing={previewing}
              apiKey={apiKey}
            />
          ) : null}
          {tab === "response" ? <ResponseView apiKey={apiKey} console={data} result={result} /> : null}
          {tab === "history" ? <ApiHistory apiKey={apiKey} card={card} version={result?.called_at} /> : null}
          {tab === "docs" ? <DocsView apiKey={apiKey} /> : null}
        </ModalTabs>
      ) : null}
    </Modal>
  );
}
