"use client";

/**
 * The ownership dialogs (design portal-cases, decision 7), shared by the inbox and the case page: Claim, Dismiss,
 * Suggest department, Allot, Take over, Stop watching, Request transfer, Accept / Decline and Withdraw. Nothing is
 * claimed, allotted or transferred without the user pressing the button and confirming here; nothing is pre-selected
 * that would claim for a department the user did not choose. Every refusal shows the API's code as a message, then the
 * inbox lists, the counts, the case and the dashboard are read again. There is no release or return-to-pool action.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { CheckField, ConfirmDialog, SelectField, TextArea, type Option } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, INBOX_KEY, useDepartmentPeople, useDepartments, useMe } from "@/lib/api/hooks";
import type { Ownership, Recipient } from "@/lib/api/types";
import { canIn, isSuperAdmin } from "@/lib/can";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

const MAX_REASON = 500;
const KEEP = "__keep__";
const CLEAR = "__clear__";

/** Runs one ownership call and re-reads everything it may change, on success and on refusal. */
export function useOwnershipCall(caseRef: string | null) {
  const queryClient = useQueryClient();
  const action = useAction();
  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: INBOX_KEY }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      caseRef ? queryClient.invalidateQueries({ queryKey: caseKey(caseRef) }) : Promise.resolve(),
    ]);
  }
  async function call(path: string, body: unknown = {}): Promise<{ ok: boolean; error: unknown }> {
    let caught: unknown = null;
    const out = await action.run(async () => {
      try {
        return await api<unknown>(path, { method: "POST", body });
      } catch (e) {
        caught = e;
        throw e;
      }
    });
    await refresh();
    return { ok: out.ok, error: caught };
  }
  return { ...action, call };
}

function casePathOf(caseRef: string, tail: string): string {
  return `${apiCasePath(caseRef)}/${tail}`;
}

function departmentOptions(codes: { code: string; name: string }[], exclude: (string | null | undefined)[] = []): Option[] {
  return codes.filter((d) => !exclude.includes(d.code)).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` }));
}

function officerOptions(items: Recipient[] | undefined): Option[] {
  const seen = new Set<string>();
  const out: Option[] = [];
  for (const p of items ?? []) {
    if (seen.has(p.user_id)) continue;
    seen.add(p.user_id);
    out.push({
      value: p.user_id,
      label: [p.full_name, p.designation, p.office_code].filter(Boolean).join(", "),
    });
  }
  return out;
}

interface BaseProps {
  open: boolean;
  caseRef: string;
  onClose: () => void;
  onDone?: () => void;
}

// ------------------------------------------------------------------------------------------------ claim

export function ClaimDialog({
  open,
  caseRef,
  onClose,
  onDone,
  department,
  departments,
  currentOwner,
}: BaseProps & {
  /** From the inbox: the selected department (always sent as `office_code`). */
  department?: string | null;
  /** From the case page: `actions.claim_departments` (null: the super admin, who names any department). */
  departments?: string[] | null;
  currentOwner?: string | null;
}) {
  const me = useMe();
  const fixed = department ?? (departments && departments.length === 1 ? departments[0]! : null);
  const [chosen, setChosen] = useState("");
  const [candidates, setCandidates] = useState<string[] | null>(null);
  const [note, setNote] = useState("");
  const [unit, setUnit] = useState("");
  const [officer, setOfficer] = useState("");
  const [missing, setMissing] = useState(false);
  const run = useOwnershipCall(caseRef);
  const anyDepartment = !department && departments === null;
  const all = useDepartments(open && anyDepartment);
  const office = fixed ?? (chosen || null);
  const canAllot = !!office && (canIn(me.data, office, "cases.allot") || isSuperAdmin(me.data));
  const people = useDepartmentPeople(office, open && canAllot);
  let pickList: Option[] | null = null;
  if (candidates) pickList = candidates.map((c) => ({ value: c, label: c }));
  else if (!fixed && departments && departments.length > 1) pickList = departments.map((c) => ({ value: c, label: c }));
  else if (!fixed && anyDepartment) pickList = departmentOptions(all.data?.departments ?? []);

  async function confirm() {
    const code = candidates ? chosen || null : office;
    if (pickList && !code) {
      setMissing(true);
      return;
    }
    const body: Record<string, unknown> = { office_code: code ?? undefined, note: note.trim() || undefined };
    if (canAllot && unit) body.unit_code = unit;
    if (canAllot && officer) body.officer_user_id = officer;
    const out = await run.call(casePathOf(caseRef, "claim"), body);
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    // office_required opens the department choice instead of failing
    const e = out.error;
    if (e instanceof ApiError && e.code === "office_required" && Array.isArray(e.extra.candidates)) {
      const list = e.extra.candidates as string[];
      if (list.length > 0) {
        setCandidates(list);
        setChosen("");
      }
    }
  }
  const err = run.error;
  return (
    <ConfirmDialog
      open={open}
      title={T.own.claimTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={err}
      confirmLabel={T.own.claim}
    >
      {currentOwner ? <p>{T.own.claimWatcher(currentOwner)}</p> : null}
      {fixed && !candidates ? (
        <p>
          {T.own.claimFor}: <strong className="mono">{fixed}</strong>
        </p>
      ) : null}
      {pickList ? (
        <SelectField
          label={T.own.claimFor}
          options={pickList}
          placeholder={T.inbox.chooseDepartment}
          value={chosen}
          error={missing && !chosen ? T.own.chooseTarget : undefined}
          onChange={(e) => {
            setChosen(e.target.value);
            setUnit("");
            setOfficer("");
          }}
        />
      ) : null}
      <TextArea label={T.own.claimNote} maxLength={MAX_REASON} value={note} onChange={(e) => setNote(e.target.value)} />
      {canAllot ? (
        <fieldset className="stack">
          <legend>{T.own.allotOptional}</legend>
          <SelectField
            label={T.own.unit}
            options={(people.data?.units ?? []).map((u) => ({ value: u.code, label: `${u.code} — ${u.name}` }))}
            placeholder={T.own.noUnit}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
          <SelectField
            label={T.own.officer}
            options={officerOptions(people.data?.items)}
            placeholder={T.own.noOfficer}
            value={officer}
            onChange={(e) => setOfficer(e.target.value)}
          />
        </fieldset>
      ) : null}
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------------------------------------ dismiss / suggest

export function DismissDialog({
  open,
  caseRef,
  onClose,
  onDone,
  department,
}: BaseProps & {
  /** From the inbox: the selected department, sent as `office_code` so the API dismisses that department's
   * recommendation and not the primary membership's (design portal-cases, deviation 10). */
  department?: string | null;
}) {
  const [reason, setReason] = useState("");
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    const out = await run.call(casePathOf(caseRef, "dismiss"), {
      office_code: department ?? undefined,
      reason: reason.trim() || undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.dismissTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.dismiss}
    >
      <TextArea label={T.own.dismissReason} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ConfirmDialog>
  );
}

export function SuggestDialog({ open, caseRef, onClose, onDone, exclude }: BaseProps & { exclude?: string | null }) {
  const departments = useDepartments(open);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    setTried(true);
    if (!target || !reason.trim()) return;
    const out = await run.call(casePathOf(caseRef, "suggest"), { office_code: target, reason: reason.trim() });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.suggestTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.suggest}
    >
      <SelectField
        label={T.own.target}
        options={departmentOptions(departments.data?.departments ?? [], [exclude])}
        placeholder={T.inbox.chooseDepartment}
        value={target}
        error={tried && !target ? T.own.chooseTarget : undefined}
        onChange={(e) => setTarget(e.target.value)}
      />
      <TextArea
        label={T.own.reasonRequired}
        maxLength={MAX_REASON}
        value={reason}
        error={tried && !reason.trim() ? T.own.reasonMissing : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------------------------------------ allot / take over / stop watching

export function AllotDialog({
  open,
  caseRef,
  onClose,
  onDone,
  department,
  current,
}: BaseProps & {
  /** The department whose row is allotted; always sent as `office_code` (design portal-cases, deviation 10). */
  department: string;
  current?: Pick<Ownership, "unit" | "officer"> | null;
}) {
  const people = useDepartmentPeople(department, open);
  const [unit, setUnit] = useState(KEEP);
  const [officer, setOfficer] = useState(KEEP);
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    const body: Record<string, unknown> = { office_code: department };
    if (unit !== KEEP) body.unit_code = unit === CLEAR ? null : unit;
    if (officer !== KEEP) body.officer_user_id = officer === CLEAR ? null : officer;
    const out = await run.call(casePathOf(caseRef, "allot"), body);
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  const keep = (label: string | null | undefined) => `${T.own.keep}${label ? ` (${label})` : ""}`;
  return (
    <ConfirmDialog
      open={open}
      title={T.own.allotTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.allot}
      confirmDisabled={unit === KEEP && officer === KEEP}
    >
      <SelectField
        label={T.own.unit}
        options={[
          { value: KEEP, label: keep(current?.unit?.code) },
          { value: CLEAR, label: T.own.clearValue },
          ...(people.data?.units ?? []).map((u) => ({ value: u.code, label: `${u.code} — ${u.name}` })),
        ]}
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
      />
      <SelectField
        label={T.own.officer}
        options={[
          { value: KEEP, label: keep(current?.officer?.full_name) },
          { value: CLEAR, label: T.own.clearValue },
          ...officerOptions(people.data?.items),
        ]}
        value={officer}
        onChange={(e) => setOfficer(e.target.value)}
      />
    </ConfirmDialog>
  );
}

export function TakeOverDialog({
  open,
  caseRef,
  onClose,
  onDone,
  officer,
}: BaseProps & { officer: { id: string; full_name: string } }) {
  const [reason, setReason] = useState("");
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    const out = await run.call(casePathOf(caseRef, "take-over"), {
      expected_officer_user_id: officer.id,
      reason: reason.trim() || undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.takeOverTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.takeOver}
    >
      <p>{T.own.takeOverText(officer.full_name)}</p>
      <TextArea label={T.own.takeOverReason} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ConfirmDialog>
  );
}

export function StopWatchingDialog({ open, caseRef, onClose, onDone }: BaseProps) {
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    setTried(true);
    if (!reason.trim()) return;
    const out = await run.call(casePathOf(caseRef, "stop-watching"), { reason: reason.trim() });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.stopTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.stopWatching}
      danger
    >
      <TextArea
        label={T.own.reasonRequired}
        maxLength={MAX_REASON}
        value={reason}
        error={tried && !reason.trim() ? T.own.reasonMissing : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------------------------------------ transfers

export function TransferDialog({ open, caseRef, onClose, onDone, exclude }: BaseProps & { exclude?: string | null }) {
  const departments = useDepartments(open);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [stay, setStay] = useState(false);
  const [tried, setTried] = useState(false);
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    setTried(true);
    if (!target || !reason.trim()) return;
    const out = await run.call(casePathOf(caseRef, "transfers"), {
      to_office_code: target,
      reason: reason.trim(),
      stay_as_watcher: stay,
    });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.transferTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.requestTransfer}
    >
      <SelectField
        label={T.own.target}
        options={departmentOptions(departments.data?.departments ?? [], [exclude])}
        placeholder={T.inbox.chooseDepartment}
        value={target}
        error={tried && !target ? T.own.chooseTarget : undefined}
        onChange={(e) => setTarget(e.target.value)}
      />
      <TextArea
        label={T.own.reasonRequired}
        maxLength={MAX_REASON}
        value={reason}
        error={tried && !reason.trim() ? T.own.reasonMissing : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      <CheckField label={T.own.stayWatcher} checked={stay} onChange={(e) => setStay(e.target.checked)} />
    </ConfirmDialog>
  );
}

export function DecideDialog({
  open,
  caseRef,
  onClose,
  onDone,
  transferId,
  accept,
}: BaseProps & { transferId: string; accept: boolean }) {
  const [note, setNote] = useState("");
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    const out = await run.call(`/transfers/${encodeURIComponent(transferId)}/${accept ? "accept" : "decline"}`, {
      note: note.trim() || undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.decideTitle(accept)}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={accept ? T.own.accept : T.own.decline}
      danger={!accept}
    >
      <TextArea label={T.own.decideNote} maxLength={MAX_REASON} value={note} onChange={(e) => setNote(e.target.value)} />
    </ConfirmDialog>
  );
}

export function WithdrawDialog({ open, caseRef, onClose, onDone, transferId }: BaseProps & { transferId: string }) {
  const run = useOwnershipCall(caseRef);
  async function confirm() {
    const out = await run.call(`/transfers/${encodeURIComponent(transferId)}/withdraw`);
    if (out.ok) {
      onDone?.();
      onClose();
    }
  }
  return (
    <ConfirmDialog
      open={open}
      title={T.own.withdrawTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.withdraw}
      danger
    >
      <p>{T.own.withdrawText}</p>
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------------------------------------ one open dialog at a time

export type DialogKind =
  | { kind: "claim"; caseRef: string; currentOwner?: string | null; departments?: string[] | null }
  | { kind: "dismiss"; caseRef: string }
  | { kind: "suggest"; caseRef: string }
  | { kind: "allot"; caseRef: string; current?: Pick<Ownership, "unit" | "officer"> | null; department: string }
  | { kind: "take_over"; caseRef: string; officer: { id: string; full_name: string } }
  | { kind: "stop_watching"; caseRef: string }
  | { kind: "transfer"; caseRef: string }
  | { kind: "decide"; caseRef: string; transferId: string; accept: boolean }
  | { kind: "withdraw"; caseRef: string; transferId: string };

/** Renders the one open dialog; `department` is the acting department where the screen knows it (the inbox). */
export function OwnershipDialogs({
  open,
  onClose,
  department,
  onDone,
}: {
  open: DialogKind | null;
  onClose: () => void;
  department?: string | null;
  onDone?: () => void;
}) {
  if (!open) return null;
  const common = { open: true, caseRef: open.caseRef, onClose, onDone };
  switch (open.kind) {
    case "claim":
      return (
        <ClaimDialog
          {...common}
          department={open.departments !== undefined ? undefined : department}
          departments={open.departments}
          currentOwner={open.currentOwner}
        />
      );
    case "dismiss":
      return <DismissDialog {...common} department={department} />;
    case "suggest":
      return <SuggestDialog {...common} exclude={department} />;
    case "allot":
      return <AllotDialog {...common} department={open.department} current={open.current} />;
    case "take_over":
      return <TakeOverDialog {...common} officer={open.officer} />;
    case "stop_watching":
      return <StopWatchingDialog {...common} />;
    case "transfer":
      return <TransferDialog {...common} exclude={department} />;
    case "decide":
      return <DecideDialog {...common} transferId={open.transferId} accept={open.accept} />;
    case "withdraw":
      return <WithdrawDialog {...common} transferId={open.transferId} />;
  }
}
