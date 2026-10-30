"use client";

/**
 * Controls of the UI kit (design portal-ui-redesign, decisions 14 and 17): buttons, labelled fields, check and radio
 * fields, the file field, chips, removable filter chips and the two- or three-way switch. One control height
 * (`--control-h`, 36 px) for every button, input and select; the `sm` button (30 px) is only for toolbars inside a
 * row. Keyboard and screen-reader friendly: labels on every field, `aria-live` errors, visible focus. A `Button`
 * carries `data-ui="button"`, `data-variant` and `data-size`, and the text, select and textarea controls carry
 * `data-ui="field"`, so the browser check can measure them (design portal-ui-polish, decision 21).
 */
import {
  useId,
  useRef,
  useState,
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
      data-ui="button"
      data-variant={variant}
      data-size={variant !== "link" ? size : undefined}
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
  /** The label kept for screen readers but not drawn (a one-line toolbar, where the placeholder shows it). */
  hideLabel?: boolean;
}

export function useFieldIds(id?: string) {
  const auto = useId();
  const base = id ?? auto;
  return { id: base, hint: `${base}-hint`, error: `${base}-error` };
}

function describedBy(ids: { hint: string; error: string }, hint?: ReactNode, error?: ReactNode) {
  return [hint ? ids.hint : null, error ? ids.error : null].filter(Boolean).join(" ") || undefined;
}

function FieldFrame({
  ids,
  label,
  hint,
  error,
  hideLabel,
  children,
}: FieldShell & { ids: ReturnType<typeof useFieldIds>; children: ReactNode }) {
  return (
    <div className={s.field}>
      <label className={cx(s.label, hideLabel && "visually-hidden")} htmlFor={ids.id}>
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

export function TextField({ label, hint, error, hideLabel, id, className, ...rest }: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const ids = useFieldIds(id);
  const [shown, setShown] = useState(false);
  const isPassword = rest.type === "password";
  const input = (
    <input
      id={ids.id}
      className={cx(s.input, s.control, isPassword && s.withReveal, className)}
      data-ui="field"
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy(ids, hint, error)}
      {...rest}
      type={isPassword && shown ? "text" : rest.type}
    />
  );
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error} hideLabel={hideLabel}>
      {isPassword ? (
        // every password field can be shown while typing; the button is a toggle, so a screen reader hears its state
        <div className={s.reveal}>
          {input}
          <button
            type="button"
            className={s.revealButton}
            aria-label={shown ? T.hidePassword : T.showPassword}
            aria-pressed={shown}
            aria-controls={ids.id}
            disabled={rest.disabled}
            onClick={() => setShown((v) => !v)}
          >
            <EyeIcon off={shown} />
          </button>
        </div>
      ) : (
        input
      )}
    </FieldFrame>
  );
}

function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {off ? <path d="M3 3l18 18" /> : null}
    </svg>
  );
}

export function TextArea({ label, hint, error, hideLabel, id, ...rest }: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error} hideLabel={hideLabel}>
      <textarea
        id={ids.id}
        className={cx(s.input, s.textarea)}
        data-ui="field"
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
  hideLabel,
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
    <FieldFrame ids={ids} label={label} hint={hint} error={error} hideLabel={hideLabel}>
      <select
        id={ids.id}
        className={cx(s.input, s.select, s.control)}
        data-ui="field"
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

/**
 * A checkbox with its label. `inline` (design portal-ui-polish-2, decision 26) is for a checkbox in a row of labelled
 * fields: it sits on the 36 px control line, level with the boxes and the Search button, not with the labels.
 */
export function CheckField({
  label,
  id,
  inline,
  ...rest
}: { label: ReactNode; inline?: boolean } & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const fieldId = id ?? auto;
  return (
    <div className={cx(s.check, inline && s.checkInline)} data-inline={inline || undefined}>
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
  hint,
}: {
  on?: boolean;
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
  /** What the chip keeps, as the button's description and tooltip (design case-inbox-simplify, decision 10). */
  hint?: string;
}) {
  const hintId = useId();
  return (
    <>
      <button
        type="button"
        className={cx(s.chip, on && s.chipOn)}
        aria-pressed={!!on}
        onClick={onClick}
        disabled={disabled}
        title={hint}
        aria-describedby={hint ? hintId : undefined}
      >
        {children}
      </button>
      {hint ? (
        <span id={hintId} className="visually-hidden">
          {hint}
        </span>
      ) : null}
    </>
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
  describedBy,
}: {
  label: string;
  /** `title` is the option's tooltip; a `disabled` option is shown but cannot be chosen (design portal-ui-polish-2). */
  options: (Option & { title?: string; disabled?: boolean })[];
  value: string;
  onChange: (value: string) => void;
  /** The id of the line that says what the chosen option shows. */
  describedBy?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    let next = index;
    for (let step = 0; step < options.length; step++) {
      next = (next + delta + options.length) % options.length;
      if (!options[next]!.disabled) break;
    }
    if (next === index) return;
    onChange(options[next]!.value);
    refs.current[next]?.focus();
  }
  return (
    <div role="radiogroup" aria-label={label} aria-describedby={describedBy} className={s.segmented}>
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
            title={o.title}
            // aria-disabled, not disabled: the tooltip saying why still shows on pointer and focus
            aria-disabled={o.disabled || undefined}
            className={cx(s.segment, checked && s.segmentOn)}
            onClick={() => (o.disabled ? undefined : onChange(o.value))}
            onKeyDown={(e) => onKey(e, i)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * A labelled `SegmentedSwitch` for a field row (design case-workspace-admin, decision 17: "Held by: Me / My offices"):
 * the label on the fields' label line, so its top meets the other labels and the switch's top meets the boxes.
 */
export function SegmentedField({
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
  const id = useId();
  return (
    <div className={s.field} data-ui="segmented-field">
      <label className={s.label} id={id}>
        {label}
      </label>
      <SegmentedSwitch label={label} options={options} value={value} onChange={onChange} />
    </div>
  );
}

/**
 * An on/off switch (`role="switch"`, design case-workspace-admin, decision 25): a button whose `aria-checked` is the
 * state; Space and Enter toggle it as any button. `label` is its accessible name, `describedBy` the line under it.
 */
export function Switch({
  checked,
  onChange,
  label,
  describedBy,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  describedBy?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      className={s.switch}
      data-ui="switch"
      onClick={() => onChange(!checked)}
    />
  );
}
