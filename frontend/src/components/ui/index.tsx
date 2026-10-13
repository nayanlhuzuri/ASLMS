"use client";

/**
 * The portal's small UI kit (design portal-shell, "Services"): labelled fields, buttons, tables, tabs, badges, a
 * dialog, tiles, empty states, the error banner and pagination. Plain CSS Modules; keyboard and screen-reader
 * friendly (labels, `aria-live` errors, visible focus).
 */
import Link from "next/link";
import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type Ref,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { formatNumber } from "@/lib/format";
import { errorText, T, type ErrorTexts } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { signalText, type Signal } from "@/lib/signals";

import s from "./ui.module.css";

function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "link";
  busy?: boolean;
};

export function Button({ variant = "primary", busy, disabled, className, children, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={cx(s.button, variant !== "primary" && s[variant], className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}

interface FieldShell {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
}

function useFieldIds(id?: string) {
  const auto = useId();
  const base = id ?? auto;
  return { id: base, hint: `${base}-hint`, error: `${base}-error` };
}

function describedBy(ids: { hint: string; error: string }, hint?: ReactNode, error?: ReactNode) {
  return [hint ? ids.hint : null, error ? ids.error : null].filter(Boolean).join(" ") || undefined;
}

function FieldFrame({ ids, label, hint, error, children }: FieldShell & { ids: ReturnType<typeof useFieldIds>; children: ReactNode }) {
  return (
    <div className={s.field}>
      <label className={s.label} htmlFor={ids.id}>
        {label}
      </label>
      {children}
      {hint ? (
        <span id={ids.hint} className={s.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={ids.error} className={s.error} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export function TextField({ label, hint, error, id, className, ...rest }: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <input
        id={ids.id}
        className={cx(s.input, className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, hint, error)}
        {...rest}
      />
    </FieldFrame>
  );
}

export function TextArea({ label, hint, error, id, ...rest }: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <textarea
        id={ids.id}
        className={s.input}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, hint, error)}
        {...rest}
      />
    </FieldFrame>
  );
}

export interface Option {
  value: string;
  label: string;
}

export function SelectField({
  label,
  hint,
  error,
  id,
  options,
  groups,
  placeholder,
  ...rest
}: FieldShell &
  SelectHTMLAttributes<HTMLSelectElement> & {
    options: Option[];
    /** Options under `<optgroup>` headings, after `options`. */
    groups?: { label: string; options: Option[] }[];
    placeholder?: string;
  }) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <select
        id={ids.id}
        className={s.input}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, hint, error)}
        {...rest}
      >
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        {(groups ?? []).map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </FieldFrame>
  );
}

export function CheckField({ label, id, ...rest }: { label: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const fieldId = id ?? auto;
  return (
    <div className={s.check}>
      <input id={fieldId} type="checkbox" {...rest} />
      <label htmlFor={fieldId}>{label}</label>
    </div>
  );
}

export function Table({ caption, children }: { caption?: ReactNode; children: ReactNode }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className={s.table}>
        {caption ? <caption>{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export const numCell = s.num;

export interface TabItem {
  href: string;
  label: string;
  active: boolean;
}

export function Tabs({ items, label }: { items: TabItem[]; label: string }) {
  return (
    <nav aria-label={label} className={s.tabs}>
      {items.map((t) => (
        <Link key={t.href} href={t.href} className={s.tab} aria-current={t.active ? "page" : undefined}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

export function Badge({ tone, children }: { tone?: "danger" | "warning" | "success"; children: ReactNode }) {
  return <span className={cx(s.badge, tone && s[`badge-${tone}`])}>{children}</span>;
}

export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // the latest onClose, so a parent's new function on each render does not move the focus back to the start
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, select, textarea, button");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key !== "Tab" || !ref.current) return;
      // keep the focus inside the dialog (WCAG 2.1: a modal dialog traps focus)
      const focusable = Array.from(
        ref.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"),
      );
      if (focusable.length === 0) return;
      const firstEl = focusable[0]!;
      const lastEl = focusable[focusable.length - 1]!;
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open]);
  if (!open) return null;
  return (
    <div className={s.overlay}>
      <div ref={ref} className={s.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className={s.dialogHead}>
          <h2 id={titleId}>{title}</h2>
          <Button variant="link" onClick={onClose} aria-label={T.close}>
            {T.close}
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** A figure with its label; with `href` the whole tile is one link named by its label and value. */
export function Tile({
  label,
  value,
  sub,
  href,
}: {
  label: string;
  value: number | null | undefined;
  sub?: ReactNode;
  href?: string;
}) {
  const body = (
    <>
      <div className={s.tileValue}>{formatNumber(value)}</div>
      <div className={s.tileLabel}>{label}</div>
      {sub ? <div className={s.tileSub}>{sub}</div> : null}
    </>
  );
  if (href) {
    return (
      <Link href={href} className={cx(s.tile, s.tileLink)} aria-label={`${label}: ${formatNumber(value)}`}>
        {body}
      </Link>
    );
  }
  return <div className={s.tile}>{body}</div>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className={s.empty}>{children}</div>;
}

export function ErrorBanner({
  error,
  onRetry,
  messages,
  children,
}: {
  error: unknown;
  onRetry?: () => void;
  /** The screen's own texts for codes that mean something else elsewhere (design portal-workflow, decision 21). */
  messages?: ErrorTexts;
  /** More after the message (a link to an existing document, for example). */
  children?: ReactNode;
}) {
  if (!error) return null;
  return (
    <div className={s.banner} role="alert" aria-live="assertive">
      <span>{errorText(error, messages)}</span>
      {children}
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          {T.retry}
        </Button>
      ) : null}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className={s.notice} role="status" aria-live="polite">
      {children}
    </div>
  );
}

export function Loading() {
  return (
    <p className="muted" role="status" aria-live="polite">
      {T.loading}
    </p>
  );
}

export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const to = Math.min(offset + limit, total);
  return (
    <div className={s.pagination}>
      <span className="muted">{T.pageOf(offset + 1, to, formatNumber(total))}</span>
      <Button variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        {T.previous}
      </Button>
      <Button variant="secondary" disabled={to >= total} onClick={() => onChange(offset + limit)}>
        {T.next}
      </Button>
    </div>
  );
}

/**
 * The score as stored (three decimals) with the label of the API's `band` (STRONG / POSSIBLE): the colour and the
 * label never come from the portal comparing numbers, because the bands are the super admin's settings.
 */
export function ScoreBadge({ score, band }: { score: number; band: string }) {
  const label = band === "high" ? "STRONG" : band === "medium" ? "POSSIBLE" : band.toUpperCase();
  return (
    <span className={cx(s.score, (band === "high" || band === "medium") && s[`score-${band}`])}>
      <span>{score.toFixed(3)}</span>
      <span className={s.scoreLabel}>{label}</span>
    </span>
  );
}

export function SignalChip({ signal }: { signal: Signal }) {
  return <span className={s.chip}>{signalText(signal)}</span>;
}

export function SignalChips({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  return (
    <ul className={s.chips} aria-label="Signals">
      {signals.map((sig, i) => (
        <li key={i}>
          <SignalChip signal={sig} />
        </li>
      ))}
    </ul>
  );
}

export interface CaseRefLike {
  ref_no: string;
  cnr?: string | null;
  case_no_text?: string | null;
}

/**
 * A case reference (case number, else `ref_no`; monospace; the CNR as its title) as a link to the case page. A case
 * the caller cannot open (`visible: false`) is plain text, never a link, because opening it answers 404.
 */
export function CaseLink({ value, visible = true }: { value: CaseRefLike | null | undefined; visible?: boolean }) {
  if (!value) return <span>—</span>;
  const text = value.case_no_text || value.ref_no;
  if (!visible) {
    return (
      <span className="mono" title={value.cnr ?? undefined}>
        {text}
      </span>
    );
  }
  return (
    <Link href={casePath(value.ref_no)} className="mono" title={value.cnr ?? undefined}>
      {text}
    </Link>
  );
}

export function DefinitionList({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className={s.dl}>
      {items.map(([label, value], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === "" ? "—" : value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A dialog that asks before an action: its fields, the API's refusal, and Confirm / Cancel. */
export function ConfirmDialog({
  open,
  title,
  onClose,
  onConfirm,
  busy,
  error,
  confirmLabel = T.own.confirm,
  confirmDisabled,
  danger,
  messages,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  onConfirm: () => void;
  busy?: boolean;
  error?: unknown;
  confirmLabel?: string;
  confirmDisabled?: boolean;
  danger?: boolean;
  messages?: ErrorTexts;
  children?: ReactNode;
}) {
  return (
    <Dialog open={open} title={title} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm();
        }}
      >
        {children}
        <ErrorBanner error={error} messages={messages} />
        <div className={s.dialogActions}>
          <Button variant="secondary" onClick={onClose}>
            {T.cancel}
          </Button>
          <Button type="submit" variant={danger ? "danger" : "primary"} busy={busy} disabled={confirmDisabled}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** The number of characters typed against the limit, read out politely (design portal-workflow, decision 25). */
export function CharCounter({ value, max, id }: { value: string; max: number; id?: string }) {
  const n = value.length;
  return (
    <span id={id} className={cx(s.hint, n > max && s.error)} aria-live="polite">
      {T.wf.characters(n, max)}
    </span>
  );
}

/** A file input with its label, hint and error; `accept` from the server's permitted extensions. */
export function FileField({
  label,
  hint,
  error,
  id,
  onFiles,
  multiple,
  accept,
  required,
  inputRef,
}: FieldShell & {
  id?: string;
  onFiles: (files: File[]) => void;
  multiple?: boolean;
  accept?: string;
  required?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <input
        ref={inputRef}
        id={ids.id}
        type="file"
        className={s.input}
        accept={accept}
        multiple={multiple}
        aria-required={required || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, hint, error)}
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      />
    </FieldFrame>
  );
}

/** The API's severity of an alert (critical / high / normal), never computed in the browser. */
export function SeverityBadge({ severity }: { severity: string }) {
  const tone = severity === "critical" ? "danger" : severity === "high" ? "warning" : undefined;
  return <Badge tone={tone}>{T.wf.severity[severity] ?? severity}</Badge>;
}

/** Radio buttons in a fieldset; nothing is selected until the user chooses (`value` empty). */
export function RadioGroup({
  legend,
  name,
  options,
  value,
  onChange,
  error,
  disabled,
}: {
  legend: ReactNode;
  name: string;
  options: (Option & { hint?: ReactNode })[];
  value: string;
  onChange: (value: string) => void;
  error?: ReactNode;
  disabled?: boolean;
}) {
  const errorId = useId();
  return (
    <fieldset className={s.radios} aria-describedby={error ? errorId : undefined}>
      <legend className={s.label}>{legend}</legend>
      {options.map((o) => {
        const id = `${name}-${o.value}`;
        return (
          <div key={o.value} className={s.check}>
            <input
              id={id}
              type="radio"
              name={name}
              value={o.value}
              checked={value === o.value}
              disabled={disabled}
              onChange={() => onChange(o.value)}
            />
            <label htmlFor={id}>
              {o.label}
              {o.hint ? <span className={s.hint}> — {o.hint}</span> : null}
            </label>
          </div>
        );
      })}
      {error ? (
        <span id={errorId} className={s.error} role="alert">
          {error}
        </span>
      ) : null}
    </fieldset>
  );
}
