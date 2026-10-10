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
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { formatNumber } from "@/lib/format";
import { errorText, T } from "@/lib/messages";

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
  placeholder,
  ...rest
}: FieldShell & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; placeholder?: string }) {
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
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, select, textarea, button");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);
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

export function Tile({ label, value, sub }: { label: string; value: number | null | undefined; sub?: ReactNode }) {
  return (
    <div className={s.tile}>
      <div className={s.tileValue}>{formatNumber(value)}</div>
      <div className={s.tileLabel}>{label}</div>
      {sub ? <div className={s.tileSub}>{sub}</div> : null}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className={s.empty}>{children}</div>;
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className={s.banner} role="alert" aria-live="assertive">
      <span>{errorText(error)}</span>
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
