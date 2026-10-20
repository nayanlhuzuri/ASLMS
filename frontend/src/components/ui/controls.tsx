"use client";

/**
 * Controls of the UI kit (design portal-ui-redesign, decisions 14 and 17): buttons, labelled fields, check and radio
 * fields, the file field, chips, removable filter chips and the two- or three-way switch. One control height
 * (`--control-h`, 36 px) for every button, input and select; the `sm` button (30 px) is only for toolbars inside a
 * row. Keyboard and screen-reader friendly: labels on every field, `aria-live` errors, visible focus.
 */
import {
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { T } from "@/lib/messages";

import s from "./controls.module.css";

export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

/** The class every 36 px control carries (tests read it; the stylesheet sets `height: var(--control-h)`). */
export const controlClass = s.control!;

/** A link drawn as a button (a toolbar's Print and Download, which open or save a file). */
export function buttonClass(variant: "primary" | "secondary" | "ghost" = "secondary", size: "md" | "sm" = "md"): string {
  return cx(s.button, size === "sm" ? s.sm : s.control, s[variant]);
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "link";
  size?: "md" | "sm";
  busy?: boolean;
};

export function Button({ variant = "primary", size = "md", busy, disabled, className, children, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={cx(
        s.button,
        variant !== "link" && (size === "sm" ? s.sm : s.control),
        s[variant],
        className,
      )}
      data-variant={variant}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}

export interface FieldShell {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
}

export function useFieldIds(id?: string) {
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
        className={cx(s.input, s.control, className)}
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
        className={cx(s.input, s.textarea)}
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
        className={cx(s.input, s.select, s.control)}
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
        className={cx(s.input, s.file)}
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

/** A filter chip that toggles (`aria-pressed`), 30 px high. */
export function Chip({
  on,
  onClick,
  children,
  disabled,
}: {
  on?: boolean;
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button type="button" className={cx(s.chip, on && s.chipOn)} aria-pressed={!!on} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

/** A labelled row of chips. */
export function ChipGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className={s.chips}>
      {children}
    </div>
  );
}

/** An active filter as a removable chip (26 px); the button's name says which filter it removes. */
export function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className={s.filterChip}>
      <span>{label}</span>
      <button type="button" aria-label={T.kit.removeFilter(label)} onClick={onRemove}>
        <span aria-hidden="true">×</span>
      </button>
    </span>
  );
}

/**
 * A two- or three-way switch (`role="radiogroup"`, decision 17): one option is always chosen; the arrow keys move
 * the choice, as radio buttons do.
 */
export function SegmentedSwitch({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Option[];
  value: string;
  onChange: (value: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = (index + delta + options.length) % options.length;
    onChange(options[next]!.value);
    refs.current[next]?.focus();
  }
  return (
    <div role="radiogroup" aria-label={label} className={s.segmented}>
      {options.map((o, i) => {
        const checked = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            className={cx(s.segment, checked && s.segmentOn)}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
