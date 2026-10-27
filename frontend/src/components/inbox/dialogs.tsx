"use client";

/**
 * The ownership dialogs (design portal-cases, decision 7), shared by the inbox and the case page: Claim, Dismiss,
 * Suggest department, Assign (`allot`), Take over, Stop watching, Request transfer, Accept / Decline and Withdraw.
 * Nothing is claimed, assigned or transferred without the user pressing the button and confirming here; nothing is
 * pre-selected that would claim for a department the user did not choose. Every refusal shows the API's code as a message, then the
 * inbox lists, the counts, the case and the dashboard are read again. There is no release or return-to-pool action.
 *
 * One rule for the department that acts (design portal-cases-followups, decisions 4-6): the case page passes the
 * server's department list for the action, the inbox the selected department. One department is shown as text and
 * sent; several give a required select with nothing pre-selected; an `office_required` answer opens the same select.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { CheckField, ConfirmDialog, ErrorBanner, Loading, SelectField, TextArea, type Option } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, INBOX_KEY, useCaseTitle, useDepartmentPeople, useDepartments, useMe, useOwnership } from "@/lib/api/hooks";
import type { Ownership, Recipient, RecipientList } from "@/lib/api/types";
import { canIn, isSuperAdmin } from "@/lib/can";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import ib from "./inbox.module.css";

export const MAX_REASON = 500;
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

export function departmentOptions(codes: { code: string; name: string }[], exclude: (string | null | undefined)[] = []): Option[] {
  return codes.filter((d) => !exclude.includes(d.code)).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` }));
}

export function officerOptions(items: Recipient[] | undefined): Option[] {
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

// ------------------------------------------------------------------------------------------------ assign (codes keep "allot")

/**
 * The department's choice of who handles the case (design claim-assign-wording, decisions 2 and 3): the claim dialogs'
 * "Assign Now (Optional)" heading (an `h4`, no fieldset), the explanation line, and the Responsible Unit and Dealing
 * Officer fields side by side in one field row where the dialog is wide enough, stacked below that.
 */
export function AssignSection({ heading = false, children }: { heading?: boolean; children: ReactNode }) {
  return (
    <div className="stack">
      {heading ? <h4 className={ib.assignHeading}>{T.own.assignOptional}</h4> : null}
      <p className={`muted ${ib.assignExplain}`}>{T.own.assignExplain}</p>
      <div className={`row ${ib.assignRow}`}>{children}</div>
    </div>
  );
}

/** The claim dialogs' Assign Now section: empty means Whole Department and No Dealing Officer Yet (nothing is sent). */
export function ClaimAssignNow({
  people,
  unit,
  officer,
  onUnit,
  onOfficer,
}: {
  people: RecipientList | undefined;
  unit: string;
  officer: string;
  onUnit: (v: string) => void;
  onOfficer: (v: string) => void;
}) {
  return (
    <AssignSection heading>
      <SelectField
        label={T.own.unit}
        hint={T.own.unitHint}
        options={(people?.units ?? []).map((u) => ({ value: u.code, label: `${u.code} — ${u.name}` }))}
        placeholder={T.own.noUnit}
        value={unit}
        onChange={(e) => onUnit(e.target.value)}
      />
      <SelectField
        label={T.own.officer}
        hint={T.own.officerHint}
        options={officerOptions(people?.items)}
        placeholder={T.own.noOfficer}
        value={officer}
        onChange={(e) => onOfficer(e.target.value)}
      />
    </AssignSection>
  );
}

// ------------------------------------------------------------------------------------------------ the department that acts

/** The candidate departments of an `office_required` answer, or null for any other error. */
export function officeRequiredCandidates(error: unknown): string[] | null {
  if (error instanceof ApiError && error.code === "office_required" && Array.isArray(error.extra.candidates)) {
    const list = (error.extra.candidates as unknown[]).filter((c): c is string => typeof c === "string");
    return list.length > 0 ? list : null;
  }
  return null;
}

/**
 * The department choice of one dialog (decision 4). `departments` is the server's list for the action (the case
 * page), `fixed` the inbox's selected department. `office` is the code to send (null: send none); `check()` asks for
 * a choice when several departments are offered and none is chosen; `onError` turns an `office_required` answer into
 * the choice instead of a failure.
 */
export function useOfficeRequired(departments?: string[] | null, fixed?: string | null) {
  const [chosen, setChosen] = useState("");
  const [candidates, setCandidates] = useState<string[] | null>(null);
  const [missing, setMissing] = useState(false);
  const codes = candidates ?? (fixed ? [fixed] : (departments ?? []));
  const office = codes.length === 1 ? codes[0]! : codes.includes(chosen) ? chosen : null;
  return {
    codes,
    office,
    chosen,
    missing: missing && codes.length > 1 && !office,
    choose(code: string) {
      setChosen(code);
      setMissing(false);
    },
    check(): boolean {
      if (codes.length > 1 && !office) {
        setMissing(true);
        return false;
      }
      return true;
    },
    onError(error: unknown): boolean {
      const list = officeRequiredCandidates(error);
      if (!list) return false;
      setCandidates(list);
      setChosen("");
      setMissing(false);
      return true;
    },
  };
}

type Choice = ReturnType<typeof useOfficeRequired>;

/** One department: "For: FIN" as text; several: a required select with no pre-selection; none: nothing. */
export function DepartmentChoice({
  choice,
  label = T.own.forDepartment,
  onChange,
}: {
  choice: Choice;
  label?: string;
  onChange?: (code: string) => void;
}) {
  if (choice.codes.length === 0) return null;
  if (choice.codes.length === 1) {
    return (
      <p>
        {label}: <strong className="mono">{choice.codes[0]}</strong>
      </p>
    );
  }
  return (
    <SelectField
      label={label}
      options={choice.codes.map((c) => ({ value: c, label: c }))}
      placeholder={T.inbox.chooseDepartment}
      value={choice.office ?? ""}
      error={choice.missing ? T.own.chooseTarget : undefined}
      onChange={(e) => {
        choice.choose(e.target.value);
        onChange?.(e.target.value);
      }}
    />
  );
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
  /** From the case page: `actions.claim_departments` (null: the super admin on a pool case, any department).
   * Left out together with `department` (search results): read from `GET /cases/{ref}/ownership` (decision 7). */
  departments?: string[] | null;
  currentOwner?: string | null;
}) {
  const me = useMe();
  const fromServer = !department && departments === undefined;
  const view = useOwnership(caseRef, open && fromServer);
  const list: string[] | null | undefined = fromServer ? view.data?.actions.claim_departments : departments;
  const anyDepartment = !department && list === null;
  const choice = useOfficeRequired(list ?? [], department);
  const [chosenAny, setChosenAny] = useState("");
  const [missingAny, setMissingAny] = useState(false);
  const [note, setNote] = useState("");
  const [unit, setUnit] = useState("");
  const [officer, setOfficer] = useState("");
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  const all = useDepartments(open && anyDepartment);
  const office = anyDepartment && choice.codes.length === 0 ? chosenAny || null : choice.office;
  const canAllot = !!office && (canIn(me.data, office, "cases.allot") || isSuperAdmin(me.data));
  const people = useDepartmentPeople(office, open && canAllot);
  const owner = currentOwner !== undefined ? currentOwner : fromServer ? (view.data?.primary?.office_code ?? null) : null;
  const waiting = fromServer && (view.isPending || !!view.error);

  async function confirm() {
    if (waiting) return;
    if (anyDepartment && choice.codes.length === 0) {
      if (!chosenAny) {
        setMissingAny(true);
        return;
      }
    } else if (!choice.check()) {
      return;
    }
    const body: Record<string, unknown> = { office_code: office ?? undefined, note: note.trim() || undefined };
    if (canAllot && unit) body.unit_code = unit;
    if (canAllot && officer) body.officer_user_id = officer;
    const out = await run.call(casePathOf(caseRef, "claim"), body);
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    // office_required opens the department choice instead of failing
    if (choice.onError(out.error)) {
      setUnit("");
      setOfficer("");
    }
  }
  return (
    <ConfirmDialog
      open={open}
      subtitle={caseTitle}
      title={T.own.claimTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.claim}
      confirmDisabled={waiting || (!anyDepartment && choice.codes.length === 0)}
    >
      {fromServer && view.isPending ? <Loading /> : null}
      {fromServer && view.error instanceof ApiError && view.error.status === 404 ? (
        <p role="alert">{view.error.message}</p>
      ) : fromServer ? (
        <ErrorBanner error={view.error} />
      ) : null}
      {owner ? <p>{T.own.claimWatcher(owner)}</p> : null}
      {!waiting && !anyDepartment && choice.codes.length === 0 ? <p>{T.own.noClaimDepartment}</p> : null}
      <DepartmentChoice
        choice={choice}
        label={T.own.claimFor}
        onChange={() => {
          setUnit("");
          setOfficer("");
        }}
      />
      {anyDepartment && choice.codes.length === 0 ? (
        <SelectField
          label={T.own.claimFor}
          options={departmentOptions(all.data?.departments ?? [])}
          placeholder={T.inbox.chooseDepartment}
          value={chosenAny}
          error={missingAny && !chosenAny ? T.own.chooseTarget : undefined}
          onChange={(e) => {
            setChosenAny(e.target.value);
            setUnit("");
            setOfficer("");
          }}
        />
      ) : null}
      <TextArea label={T.own.claimNote} maxLength={MAX_REASON} value={note} onChange={(e) => setNote(e.target.value)} />
      {canAllot ? (
        <ClaimAssignNow people={people.data} unit={unit} officer={officer} onUnit={setUnit} onOfficer={setOfficer} />
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
  departments,
}: BaseProps & {
  /** From the inbox: the selected department, sent as `office_code` so the API dismisses that department's
   * recommendation and not the primary membership's (design portal-cases, deviation 10). */
  department?: string | null;
  /** From the case page: `actions.dismiss_departments`. */
  departments?: string[];
}) {
  const [reason, setReason] = useState("");
  const choice = useOfficeRequired(departments, department);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  async function confirm() {
    if (!choice.check()) return;
    const out = await run.call(casePathOf(caseRef, "dismiss"), {
      office_code: choice.office ?? undefined,
      reason: reason.trim() || undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    choice.onError(out.error);
  }
  return (
    <ConfirmDialog
      open={open}
      subtitle={caseTitle}
      title={T.own.dismissTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.dismiss}
    >
      <DepartmentChoice choice={choice} />
      <TextArea label={T.own.dismissReason} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ConfirmDialog>
  );
}

export function SuggestDialog({
  open,
  caseRef,
  onClose,
  onDone,
  from,
  departments,
  exclude = [],
}: BaseProps & {
  /** From the inbox's Recommended tab: the selected department, sent as `from_office_code`. */
  from?: string | null;
  /** From the case page: `actions.suggest_departments` (empty: sent without a department). */
  departments?: string[];
  /** Departments the target list leaves out (those holding the case: the API answers `target_owns`). */
  exclude?: (string | null | undefined)[];
}) {
  const all = useDepartments(open);
  const choice = useOfficeRequired(departments, from);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  const left = [...exclude, choice.office];
  const options = departmentOptions(all.data?.departments ?? [], left);
  const targetOk = !!target && !left.includes(target);
  async function confirm() {
    setTried(true);
    const fromOk = choice.check();
    if (!fromOk || !targetOk || !reason.trim()) return;
    const out = await run.call(casePathOf(caseRef, "suggest"), {
      office_code: target,
      reason: reason.trim(),
      from_office_code: choice.office ?? undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    choice.onError(out.error);
  }
  return (
    <ConfirmDialog
      open={open}
      subtitle={caseTitle}
      title={T.own.suggestTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.suggest}
    >
      <DepartmentChoice choice={choice} label={T.own.suggestFrom} />
      <SelectField
        label={T.own.target}
        options={options}
        placeholder={T.inbox.chooseDepartment}
        value={targetOk ? target : ""}
        error={tried && !targetOk ? T.own.chooseTarget : undefined}
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

function rowOf(rows: Ownership[] | undefined, office: string | null): Ownership | null {
  if (!office) return null;
  return rows?.find((r) => r.office_code === office) ?? null;
}

export function AllotDialog({
  open,
  caseRef,
  onClose,
  onDone,
  department,
  departments,
  rows,
  current,
}: BaseProps & {
  /** From the inbox: the department whose row is allotted; always sent as `office_code`. */
  department?: string;
  /** From the case page: `actions.allot_departments`; the chosen one is sent as `office_code`. */
  departments?: string[];
  /** The case's active ownership rows: the chosen department's current unit and officer are shown. */
  rows?: Ownership[];
  current?: Pick<Ownership, "unit" | "officer"> | null;
}) {
  const choice = useOfficeRequired(departments, department);
  const office = choice.office;
  const people = useDepartmentPeople(office, open && !!office);
  const [unit, setUnit] = useState(KEEP);
  const [officer, setOfficer] = useState(KEEP);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  const now = rows ? rowOf(rows, office) : (current ?? null);
  async function confirm() {
    if (!choice.check() || !office) return;
    const body: Record<string, unknown> = { office_code: office };
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
      subtitle={caseTitle}
      title={T.own.allotTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.allot}
      confirmDisabled={!!office && unit === KEEP && officer === KEEP}
    >
      <DepartmentChoice
        choice={choice}
        onChange={() => {
          setUnit(KEEP);
          setOfficer(KEEP);
        }}
      />
      {office ? (
        <AssignSection>
          <SelectField
            label={T.own.unit}
            hint={T.own.unitHint}
            options={[
              { value: KEEP, label: keep(now?.unit?.code) },
              { value: CLEAR, label: T.own.clearUnit },
              ...(people.data?.units ?? []).map((u) => ({ value: u.code, label: `${u.code} — ${u.name}` })),
            ]}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
          <SelectField
            label={T.own.officer}
            hint={T.own.officerHint}
            options={[
              { value: KEEP, label: keep(now?.officer?.full_name) },
              { value: CLEAR, label: T.own.clearOfficer },
              ...officerOptions(people.data?.items),
            ]}
            value={officer}
            onChange={(e) => setOfficer(e.target.value)}
          />
        </AssignSection>
      ) : null}
    </ConfirmDialog>
  );
}

export function TakeOverDialog({
  open,
  caseRef,
  onClose,
  onDone,
  departments,
  rows,
}: BaseProps & {
  /** `actions.take_over_departments`; the chosen one is sent as `office_code`. */
  departments: string[];
  /** The case's active ownership rows: the chosen department's officer is shown and sent as expected. */
  rows: Ownership[];
}) {
  const [reason, setReason] = useState("");
  const choice = useOfficeRequired(departments);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  const holder = rowOf(rows, choice.office)?.officer ?? null;
  async function confirm() {
    if (!choice.check() || !choice.office || !holder) return;
    const out = await run.call(casePathOf(caseRef, "take-over"), {
      office_code: choice.office,
      expected_officer_user_id: holder.id,
      reason: reason.trim() || undefined,
    });
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    choice.onError(out.error);
  }
  return (
    <ConfirmDialog
      open={open}
      subtitle={caseTitle}
      title={T.own.takeOverTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.takeOver}
      confirmDisabled={!!choice.office && !holder}
    >
      <DepartmentChoice choice={choice} />
      {holder ? <p>{T.own.takeOverText(holder.full_name)}</p> : null}
      <TextArea label={T.own.takeOverReason} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ConfirmDialog>
  );
}

export function StopWatchingDialog({
  open,
  caseRef,
  onClose,
  onDone,
  departments,
}: BaseProps & { /** From the case page: `actions.stop_watching_departments`. */ departments?: string[] }) {
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const choice = useOfficeRequired(departments);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  async function confirm() {
    setTried(true);
    const fromOk = choice.check();
    if (!fromOk || !reason.trim()) return;
    const out = await run.call(casePathOf(caseRef, "stop-watching"), {
      office_code: choice.office ?? undefined,
      reason: reason.trim(),
    });
    if (out.ok) {
      onDone?.();
      onClose();
      return;
    }
    choice.onError(out.error);
  }
  return (
    <ConfirmDialog
      open={open}
      subtitle={caseTitle}
      title={T.own.stopTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.stopWatching}
      danger
    >
      <DepartmentChoice choice={choice} />
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

export function TransferDialog({
  open,
  caseRef,
  onClose,
  onDone,
  exclude = [],
}: BaseProps & { /** Departments the target list leaves out (`actions.transfer_from`). */ exclude?: (string | null | undefined)[] }) {
  const departments = useDepartments(open);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [stay, setStay] = useState(false);
  const [tried, setTried] = useState(false);
  const run = useOwnershipCall(caseRef);
  const caseTitle = useCaseTitle(caseRef);
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
      subtitle={caseTitle}
      title={T.own.transferTitle}
      onClose={onClose}
      onConfirm={confirm}
      busy={run.busy}
      error={run.error}
      confirmLabel={T.own.requestTransfer}
    >
      <SelectField
        label={T.own.target}
        options={departmentOptions(departments.data?.departments ?? [], exclude)}
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
  const caseTitle = useCaseTitle(caseRef);
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
      subtitle={caseTitle}
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
  const caseTitle = useCaseTitle(caseRef);
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
      subtitle={caseTitle}
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
  | { kind: "dismiss"; caseRef: string; departments?: string[] }
  | {
      kind: "suggest";
      caseRef: string;
      departments?: string[];
      from?: string | null;
      exclude?: (string | null | undefined)[];
    }
  | {
      kind: "allot";
      caseRef: string;
      department?: string;
      departments?: string[];
      rows?: Ownership[];
      current?: Pick<Ownership, "unit" | "officer"> | null;
    }
  | { kind: "take_over"; caseRef: string; departments: string[]; rows: Ownership[] }
  | { kind: "stop_watching"; caseRef: string; departments?: string[] }
  | { kind: "transfer"; caseRef: string; exclude?: (string | null | undefined)[] }
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
      return (
        <DismissDialog
          {...common}
          department={open.departments !== undefined ? undefined : department}
          departments={open.departments}
        />
      );
    case "suggest":
      return <SuggestDialog {...common} from={open.from} departments={open.departments} exclude={open.exclude} />;
    case "allot":
      return (
        <AllotDialog
          {...common}
          department={open.department}
          departments={open.departments}
          rows={open.rows}
          current={open.current}
        />
      );
    case "take_over":
      return <TakeOverDialog {...common} departments={open.departments} rows={open.rows} />;
    case "stop_watching":
      return <StopWatchingDialog {...common} departments={open.departments} />;
    case "transfer":
      return <TransferDialog {...common} exclude={open.exclude ?? [department]} />;
    case "decide":
      return <DecideDialog {...common} transferId={open.transferId} accept={open.accept} />;
    case "withdraw":
      return <WithdrawDialog {...common} transferId={open.transferId} />;
  }
}
