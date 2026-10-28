"use client";

/**
 * Pieces shared by the department mapping screens (design portal-mapping, decisions 4, 5 and 9; simplified by
 * portal-ui-polish-2, decisions 39-41; the kit's list toolbar by design list-search, decision 2): the one toolbar line
 * (search, sort, Include Deactivated, order and count), the menu of a row (Change
 * Office where the API takes it, Deactivate or Reactivate after a confirmation), the case link through search and the
 * office cell. The forms never send `notes` or `weight`: the Scoring tab is the only place for weights. Showing an
 * input or an action is convenience only: the API decides every write.
 */
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { ConfirmDialog, ListSearch, ListToolbar, Menu, OfficePicker, Switch, type MenuItem } from "@/components/ui";
import { ApiError, api } from "@/lib/api/client";
import type { OfficeChoice, OfficePurpose } from "@/lib/api/types";
import { given } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import s from "./mapping.module.css";

/** The root office (the State) among the picker's choices: the generic-code rule sends `is_generic_state` for it. */
export function isRootChoice(o: OfficeChoice | undefined): boolean {
  return !!o && o.parent_code === null;
}

/** A labelled on/off switch on the control line (Include Deactivated, Search the Court). */
export function SwitchLine({
  label,
  checked,
  onChange,
  disabled,
  title,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <span className={s.switchLine} title={title}>
      <Switch label={label} checked={checked} onChange={onChange} disabled={disabled} />
      <span aria-hidden="true" onClick={() => (disabled ? undefined : onChange(!checked))}>
        {label}
      </span>
    </span>
  );
}

/**
 * One toolbar line per tab (decision 41), now a thin wrapper over the kit's `ListToolbar` (design list-search,
 * decision 2): the search box (shown above 10 rows or while a search is set, decision 8), the Sort By select where
 * the table is drawn as cards, whatever the tab adds (the Keywords tab's kind choice), Include Deactivated, then the
 * order line and the count.
 */
export function RuleToolbar({
  searchLabel,
  placeholder,
  q,
  onQ,
  onEnter,
  inactive,
  onInactive,
  children,
  showSearch = true,
  minChars,
  busy,
  sort,
  order,
  count,
}: {
  searchLabel: string;
  placeholder: string;
  q: string;
  onQ: (q: string) => void;
  onEnter?: () => void;
  inactive: boolean;
  onInactive: (v: boolean) => void;
  children?: ReactNode;
  showSearch?: boolean;
  minChars?: number;
  busy?: boolean;
  sort?: ReactNode;
  order?: ReactNode;
  count?: ReactNode;
}) {
  return (
    <ListToolbar
      search={
        showSearch ? (
          <ListSearch label={searchLabel} placeholder={placeholder} value={q} onChange={onQ} onEnter={onEnter} minChars={minChars} busy={busy} />
        ) : null
      }
      sort={sort}
      order={order}
      count={count}
    >
      {children}
      <SwitchLine label={T.mapping.includeInactive} checked={inactive} onChange={onInactive} />
    </ListToolbar>
  );
}

/**
 * The menu of a rule's row (decision 41): Change Office (where the API takes an office change) and Deactivate or
 * Reactivate, each after its dialog. A 409 re-reads the list (`onConflict`); the API's message shows in the dialog.
 */
export function RuleMenu<R>({
  path,
  active,
  label,
  confirmText,
  onDone,
  onConflict,
  office,
}: {
  path: string;
  active: boolean;
  label: string;
  confirmText: (enable: boolean) => string;
  onDone: (row: R, what: "status" | "office") => void;
  onConflict: () => void;
  /** Change Office: the picker's purpose, the current office, and the body the API takes. */
  office?: { purpose: OfficePurpose; current: string; body: (choice: OfficeChoice | undefined, code: string) => Record<string, unknown>; kinds?: string[] };
}) {
  const [open, setOpen] = useState<"status" | "office" | null>(null);
  const enable = !active;
  const verb = enable ? T.mapping.reactivate : T.mapping.deactivate;
  const items: MenuItem[] = [];
  if (office && active) items.push({ key: "office", label: T.mapping.changeOffice, onSelect: () => setOpen("office") });
  items.push({ key: "status", label: verb, onSelect: () => setOpen("status"), danger: !enable, separator: items.length > 0 });
  return (
    <>
      <Menu
        label={T.mapping.rowActionsAria(label)}
        trigger={
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <circle cx="3" cy="8" r="1.5" />
            <circle cx="8" cy="8" r="1.5" />
            <circle cx="13" cy="8" r="1.5" />
          </svg>
        }
        triggerClassName={s.kebab}
        items={items}
      />
      {open === "status" ? (
        <StatusDialog<R>
          path={path}
          enable={enable}
          label={label}
          confirmText={confirmText}
          onClose={() => setOpen(null)}
          onDone={(r) => {
            setOpen(null);
            onDone(r, "status");
          }}
          onConflict={onConflict}
        />
      ) : null}
      {open === "office" && office ? (
        <ChangeOfficeDialog<R>
          path={path}
          label={label}
          office={office}
          onClose={() => setOpen(null)}
          onDone={(r) => {
            setOpen(null);
            onDone(r, "office");
          }}
          onConflict={onConflict}
        />
      ) : null}
    </>
  );
}

function StatusDialog<R>({
  path,
  enable,
  label,
  confirmText,
  onClose,
  onDone,
  onConflict,
}: {
  path: string;
  enable: boolean;
  label: string;
  confirmText: (enable: boolean) => string;
  onClose: () => void;
  onDone: (row: R) => void;
  onConflict: () => void;
}) {
  const action = useAction();
  const verb = enable ? T.mapping.reactivate : T.mapping.deactivate;
  async function confirm() {
    const out = await action.run(() =>
      conflictAware(() => api<R>(`${path}/${enable ? "reactivate" : "deactivate"}`, { method: "POST" }), onConflict),
    );
    if (out.ok) onDone(out.value);
  }
  return (
    <ConfirmDialog
      open
      title={enable ? T.mapping.reactivateTitle : T.mapping.deactivateTitle}
      onClose={onClose}
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
  );
}

function ChangeOfficeDialog<R>({
  path,
  label,
  office,
  onClose,
  onDone,
  onConflict,
}: {
  path: string;
  label: string;
  office: { purpose: OfficePurpose; current: string; body: (choice: OfficeChoice | undefined, code: string) => Record<string, unknown>; kinds?: string[] };
  onClose: () => void;
  onDone: (row: R) => void;
  onConflict: () => void;
}) {
  const [code, setCode] = useState<string | null>(office.current);
  const [chosen, setChosen] = useState<OfficeChoice | undefined>(undefined);
  const action = useAction();
  const id = useId();
  async function save() {
    if (!code || code === office.current) {
      onClose();
      return;
    }
    const out = await action.run(() =>
      conflictAware(() => api<R>(path, { method: "PATCH", body: office.body(chosen, code) }), onConflict),
    );
    if (out.ok) onDone(out.value);
  }
  return (
    <ConfirmDialog
      open
      title={T.mapping.changeOffice}
      subtitle={label}
      onClose={onClose}
      onConfirm={() => void save()}
      busy={action.busy}
      error={given(action.error)}
      confirmLabel={T.save}
      confirmDisabled={!code}
    >
      <OfficePicker
        id={id}
        label={T.mapping.office}
        purpose={office.purpose}
        kinds={office.kinds}
        required
        value={code}
        onChange={(c) => setCode(c)}
        onChoose={setChosen}
      />
    </ConfirmDialog>
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
