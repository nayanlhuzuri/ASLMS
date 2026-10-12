"use client";

/**
 * Pieces shared by the department mapping screens (design portal-mapping, decisions 3, 4, 5 and 9): the office
 * picker, the weight override field and cell, the deactivate / reactivate action and the case link through search.
 * Showing an input or an action is convenience only: the API decides every write.
 */
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Button, ConfirmDialog, SelectField, TextField } from "@/components/ui";
import { ApiError, api } from "@/lib/api/client";
import { useMe, useScopedOffices } from "@/lib/api/hooks";
import type { OfficeOut } from "@/lib/api/types";
import { can } from "@/lib/can";
import { given, isRootOffice, officeDepth, weightText } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import s from "./mapping.module.css";

export interface OfficeChoices {
  /** Whether the login picks from a list (`users.view`); otherwise it types the office code. */
  pick: boolean;
  offices: OfficeOut[];
  isPending: boolean;
  /** The root office when it is in the picker (the login's scope holds it). */
  root: OfficeOut | undefined;
  departments: number;
}

/** The offices a login may pick (decision 4): `GET /admin/offices` with `users.view`, else none (typed codes). */
export function useOfficeChoices(): OfficeChoices {
  const me = useMe();
  const pick = can(me.data, "users.view");
  const list = useScopedOffices(pick);
  const offices = pick && !list.isError ? (list.data ?? []).filter((o) => o.is_active !== false) : [];
  return {
    pick: pick && !list.isError,
    offices,
    isPending: me.isPending || (pick && list.isPending),
    root: offices.find((o) => isRootOffice(o)),
    departments: offices.filter((o) => o.kind === "department").length,
  };
}

export function officeLabel(o: OfficeOut): string {
  return `${"  ".repeat(officeDepth(o))}${o.name} (${o.code})`;
}

/** The office picker: a list of the scope's offices with `users.view`, else a code typed by the user. */
export function OfficePicker({
  id,
  choices,
  value,
  onChange,
  allowRoot = true,
  optional = false,
  required = false,
  label = T.mapping.office,
  hint,
  error,
}: {
  id: string;
  choices: OfficeChoices;
  value: string;
  onChange: (code: string) => void;
  allowRoot?: boolean;
  optional?: boolean;
  required?: boolean;
  label?: string;
  hint?: ReactNode;
  error?: ReactNode;
}) {
  if (choices.pick || choices.isPending) {
    const offices = choices.offices.filter((o) => allowRoot || !isRootOffice(o));
    return (
      <SelectField
        id={id}
        label={label}
        hint={hint}
        error={error}
        required={required}
        options={offices.map((o) => ({ value: o.code, label: officeLabel(o) }))}
        placeholder={optional ? T.mapping.ownDepartment : T.mapping.chooseOffice}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <TextField
      id={id}
      label={label === T.mapping.office ? T.mapping.officeCode : label}
      hint={hint ?? T.mapping.officeCodeHint}
      error={error}
      required={required}
      autoComplete="off"
      value={value}
      onChange={(e) => onChange(e.target.value.toUpperCase())}
    />
  );
}

/** The office filter of a rule list: shown when the picker holds more than one department (decision 4). */
export function OfficeFilter({ choices, value, onChange }: { choices: OfficeChoices; value: string; onChange: (code: string) => void }) {
  if (!choices.pick || choices.departments < 2) return null;
  return (
    <SelectField
      label={T.mapping.filterOffice}
      options={choices.offices.map((o) => ({ value: o.code, label: officeLabel(o) }))}
      placeholder={T.mapping.allOffices}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export interface WeightDraft {
  value: string;
  changed: boolean;
}

export function weightDraft(current: number | null | undefined): WeightDraft {
  return { value: current === null || current === undefined ? "" : String(current), changed: false };
}

/**
 * The weight override input and "Clear override" (decision 3). Rendered only for a login holding `admin.scoring`;
 * a request carries `weight` only when the input was changed (`weightBody`).
 */
export function WeightField({
  draft,
  onChange,
  mode,
  current,
}: {
  draft: WeightDraft;
  onChange: (draft: WeightDraft) => void;
  mode: "create" | "edit";
  current?: number | null;
}) {
  const clearing = mode === "edit" && draft.changed && draft.value.trim() === "" && current !== null && current !== undefined;
  return (
    <div className="row">
      <TextField
        label={T.mapping.weightOverride}
        type="number"
        step="0.001"
        min="0.001"
        max="1"
        inputMode="decimal"
        value={draft.value}
        hint={clearing ? T.mapping.overrideCleared : undefined}
        onChange={(e) => onChange({ value: e.target.value, changed: true })}
      />
      <Button
        variant="secondary"
        onClick={() => onChange(mode === "create" ? { value: "", changed: false } : { value: "", changed: true })}
      >
        {T.mapping.clearOverride}
      </Button>
    </div>
  );
}

/** The effective weight, read-only for everyone, marked "setting" or "override". */
export function WeightCell({ effective, override }: { effective: number; override: number | null | undefined }) {
  return (
    <span className={s.weight}>
      <span className="mono">{weightText(effective)}</span>
      <span className={s.source}>{override === null || override === undefined ? T.mapping.fromSetting : T.mapping.fromOverride}</span>
    </span>
  );
}

/** A case reference linked through search (decision 7): search opens the case when visible, else its public summary. */
export function SearchLink({ ref_no }: { ref_no: string | null | undefined }) {
  if (!ref_no) return <span className="muted">{T.mapping.notHeld}</span>;
  return (
    <Link href={`/search?q=${encodeURIComponent(ref_no)}`} className="mono">
      {ref_no}
    </Link>
  );
}

/**
 * Deactivate or reactivate a rule, after a confirmation (decision 5). A 409 re-reads the list (`onConflict`); the
 * API's message shows in the dialog.
 */
export function RuleStatusActions<R>({
  path,
  active,
  label,
  confirmText,
  onDone,
  onConflict,
}: {
  path: string;
  active: boolean;
  label: string;
  confirmText: (enable: boolean) => string;
  onDone: (row: R) => void;
  onConflict: () => void;
}) {
  const [open, setOpen] = useState(false);
  const action = useAction();
  const enable = !active;
  const verb = enable ? T.mapping.reactivate : T.mapping.deactivate;

  async function confirm() {
    const out = await action.run(() =>
      conflictAware(() => api<R>(`${path}/${enable ? "reactivate" : "deactivate"}`, { method: "POST" }), onConflict),
    );
    if (out.ok) {
      setOpen(false);
      onDone(out.value);
    }
  }

  return (
    <>
      <Button
        variant="link"
        aria-label={`${verb} ${label}`}
        onClick={() => {
          action.reset();
          setOpen(true);
        }}
      >
        {verb}
      </Button>
      <ConfirmDialog
        open={open}
        title={enable ? T.mapping.reactivateTitle : T.mapping.deactivateTitle}
        onClose={() => setOpen(false)}
        onConfirm={() => void confirm()}
        busy={action.busy}
        error={given(action.error)}
        confirmLabel={verb}
        danger={!enable}
      >
        <p>
          <span className="mono">{label}</span>
        </p>
        <p>{confirmText(enable)}</p>
      </ConfirmDialog>
    </>
  );
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/** Runs a write; on a 409 (already mapped, already exists, a concurrent change) calls `onConflict` (re-read) and rethrows. */
export async function conflictAware<T>(work: () => Promise<T>, onConflict: () => void): Promise<T> {
  try {
    return await work();
  } catch (error) {
    if (isConflict(error)) onConflict();
    throw error;
  }
}

/** A row's office: its name with the code. */
export function OfficeCell({ office }: { office: { code: string; name: string } }) {
  return (
    <span>
      {office.name} <span className="mono muted">({office.code})</span>
    </span>
  );
}
