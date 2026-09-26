import type { ComponentProps, InputHTMLAttributes, ReactNode } from "react";
import s from "./ui.module.css";

interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** A label wrapping its control, so the association needs no ids. */
export function Field({ label, hint, children, className }: FieldProps) {
  return (
    <label className={[s.field, className ?? ""].join(" ")}>
      <span>{label}</span>
      {children}
      {hint ? <span className={s.fieldHint}>{hint}</span> : null}
    </label>
  );
}

export function TextInput(props: ComponentProps<"input">) {
  return <input type="text" {...props} className={["input", props.className ?? ""].join(" ")} />;
}

export function Select({ children, ...props }: ComponentProps<"select">) {
  return (
    <select {...props} className={["select", props.className ?? ""].join(" ")}>
      {children}
    </select>
  );
}

export function TextArea(props: ComponentProps<"textarea">) {
  return <textarea {...props} className={["textarea", props.className ?? ""].join(" ")} />;
}

export function Check({
  label,
  ...props
}: { label: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <label className={s.check}>
      <input type="checkbox" {...props} />
      <span>{label}</span>
    </label>
  );
}

export function Radio({ label, ...props }: { label: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <label className={s.check}>
      <input type="radio" {...props} />
      <span>{label}</span>
    </label>
  );
}

export function Fieldset({ legend, children }: { legend: ReactNode; children: ReactNode }) {
  return (
    <fieldset className={s.fieldset}>
      <legend>{legend}</legend>
      {children}
    </fieldset>
  );
}

export function FormRow({ children }: { children: ReactNode }) {
  return <div className={s.formRow}>{children}</div>;
}

export function FormActions({ children }: { children: ReactNode }) {
  return <div className={s.formActions}>{children}</div>;
}
