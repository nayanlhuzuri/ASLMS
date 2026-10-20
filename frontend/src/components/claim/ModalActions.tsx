"use client";

/**
 * The modal's fixed footer (design portal-ui-redesign, decision 7): Close on the left, then the actions the server
 * allows by `GET /cases/{ref}/ownership.actions` (portal-cases decision 8) — Suggest elsewhere, Dismiss and the one
 * primary "Claim for <department>"; for a Transfers-to-us row, Decline and the primary "Accept transfer"
 * (`decide_transfer`, with the transfer's id). A State-wide reader who may not act sees Close only.
 *
 * Pressing an action opens no second dialog: the footer turns into a short inline step, sliding up, with Back and
 * Confirm. Claim: an optional note (at most 500) and, with `cases.allot` in that department, an optional unit and
 * officer; Dismiss: an optional reason; Suggest elsewhere: the target department and a required reason; Accept or
 * Decline: an optional note. The fields, limits, refusal texts and request bodies are the ownership dialogs' (portal-cases
 * decision 7); every action names the selected department; an `office_required` answer opens the department choice.
 * Confirm is refused while a call is running, so a second click never sends twice.
 */
import { useRef, useState } from "react";

import {
  DepartmentChoice,
  departmentOptions,
  MAX_REASON,
  officerOptions,
  useOfficeRequired,
  useOwnershipCall,
} from "@/components/inbox/dialogs";
import { Button, ErrorBanner, SelectField, TextArea } from "@/components/ui";
import { useDepartmentPeople, useDepartments, useMe } from "@/lib/api/hooks";
import type { OwnershipActions } from "@/lib/api/types";
import { canIn, isSuperAdmin } from "@/lib/can";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";

import s from "./claim.module.css";

export type ActionKind = "claim" | "dismiss" | "suggest" | "accept" | "decline" | "withdraw";

export interface ModalActionsProps {
  caseRef: string;
  /** The selected department of Case claim: every action names it. */
  department: string | null;
  actions: OwnershipActions | null | undefined;
  /** A Transfers-to-us row: Accept / Decline instead of the claim actions. */
  transferId?: string | null;
  /** An outgoing transfer ("From us"): Withdraw instead of Accept / Decline. */
  outgoing?: boolean;
  /** The department holding the case (left out of the Suggest targets). */
  currentOwner?: string | null;
  onClose: () => void;
  onDone: (kind: ActionKind, department: string | null) => void;
}

/** `fixed` when the server lists it for the action (or allows any department), else the server's list. */
function pick(department: string | null, list: string[] | null | undefined): { fixed: string | null; list: string[] } {
  if (department && (list === null || (list ?? []).includes(department))) return { fixed: department, list: [] };
  return { fixed: null, list: list ?? [] };
}

export function ModalActions(props: ModalActionsProps) {
  const { actions, transferId, outgoing, department, onClose } = props;
  const [step, setStep] = useState<ActionKind | null>(null);
  if (step) return <InlineStep {...props} kind={step} onBack={() => setStep(null)} />;
  const claim = pick(department, actions?.claim_departments);
  const claimCode = claim.fixed ?? (claim.list.length === 1 ? claim.list[0]! : null);
  const dismissOk = !!actions?.dismiss;
  return (
    <div className={s.footer}>
      <Button variant="secondary" onClick={onClose}>
        {T.close}
      </Button>
      <span className={s.spacer} />
      {transferId && outgoing ? (
        actions?.withdraw_transfer ? (
          <Button variant="danger" onClick={() => setStep("withdraw")}>
            {T.own.withdraw}
          </Button>
        ) : null
      ) : transferId ? (
        actions?.decide_transfer ? (
          <>
            <Button variant="secondary" onClick={() => setStep("decline")}>
              {T.claim.decline}
            </Button>
            <Button onClick={() => setStep("accept")}>{T.claim.accept}</Button>
          </>
        ) : null
      ) : (
        <>
          {actions?.suggest ? (
            <Button variant="secondary" onClick={() => setStep("suggest")}>
              {T.claim.suggest}
            </Button>
          ) : null}
          {dismissOk ? (
            <Button variant="secondary" onClick={() => setStep("dismiss")}>
              {T.claim.dismiss}
            </Button>
          ) : null}
          {actions?.claim ? (
            <Button onClick={() => setStep("claim")}>{claimCode ? T.claim.claimFor(claimCode) : T.own.claim}</Button>
          ) : null}
        </>
      )}
    </div>
  );
}

function InlineStep({
  kind,
  caseRef,
  department,
  actions,
  transferId,
  currentOwner,
  onDone,
  onBack,
}: ModalActionsProps & { kind: ActionKind; onBack: () => void }) {
  const me = useMe();
  const run = useOwnershipCall(caseRef);
  const inFlight = useRef(false);
  const claimPick = pick(department, actions?.claim_departments);
  const dismissPick = pick(department, actions?.dismiss_departments);
  const suggestPick = pick(department, actions?.suggest_departments);
  const chosen = kind === "claim" ? claimPick : kind === "dismiss" ? dismissPick : suggestPick;
  const choice = useOfficeRequired(chosen.list, chosen.fixed);
  const [note, setNote] = useState("");
  const [unit, setUnit] = useState("");
  const [officer, setOfficer] = useState("");
  const [target, setTarget] = useState("");
  const [tried, setTried] = useState(false);
  const office = choice.office;
  const canAllot = kind === "claim" && !!office && (canIn(me.data, office, "cases.allot") || isSuperAdmin(me.data));
  const people = useDepartmentPeople(office, canAllot);
  const departments = useDepartments(kind === "suggest");
  const left = [currentOwner, choice.office];
  const targets = departmentOptions(departments.data?.departments ?? [], left);
  const targetOk = !!target && !left.includes(target);

  async function send(path: string, body: Record<string, unknown>, done: string | null) {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const out = await run.call(path, body);
      if (out.ok) {
        onDone(kind, done);
        return;
      }
      if (choice.onError(out.error)) {
        setUnit("");
        setOfficer("");
      }
    } finally {
      inFlight.current = false;
    }
  }

  async function confirm() {
    if (run.busy || inFlight.current) return;
    setTried(true);
    const text = note.trim() || undefined;
    if (kind === "withdraw") {
      if (!transferId) return;
      await send(`/transfers/${encodeURIComponent(transferId)}/withdraw`, {}, department);
      return;
    }
    if (kind === "accept" || kind === "decline") {
      if (!transferId) return;
      await send(`/transfers/${encodeURIComponent(transferId)}/${kind}`, { note: text }, department);
      return;
    }
    if (!choice.check()) return;
    if (kind === "claim") {
      const body: Record<string, unknown> = { office_code: office ?? undefined, note: text };
      if (canAllot && unit) body.unit_code = unit;
      if (canAllot && officer) body.officer_user_id = officer;
      await send(apiCasePath(caseRef, "claim"), body, office);
    } else if (kind === "dismiss") {
      await send(apiCasePath(caseRef, "dismiss"), { office_code: office ?? undefined, reason: text }, office);
    } else {
      if (!targetOk || !note.trim()) return;
      await send(
        apiCasePath(caseRef, "suggest"),
        { office_code: target, reason: note.trim(), from_office_code: office ?? undefined },
        target,
      );
    }
  }

  const title = T.claim.stepTitles[kind]!;
  const confirmLabel =
    kind === "claim" && office
      ? T.claim.claimFor(office)
      : kind === "accept"
        ? T.claim.accept
        : kind === "decline"
          ? T.claim.decline
          : kind === "withdraw"
            ? T.own.withdraw
            : T.claim.confirm;
  return (
    <form
      className={s.step}
      role="group"
      aria-label={title}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void confirm();
      }}
    >
      <h3>{title}</h3>
      {kind === "claim" ? (
        <>
          {currentOwner ? <p>{T.own.claimWatcher(currentOwner)}</p> : null}
          <DepartmentChoice
            choice={choice}
            label={T.own.claimFor}
            onChange={() => {
              setUnit("");
              setOfficer("");
            }}
          />
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
        </>
      ) : null}
      {kind === "dismiss" ? (
        <>
          <DepartmentChoice choice={choice} />
          <TextArea label={T.own.dismissReason} maxLength={MAX_REASON} value={note} onChange={(e) => setNote(e.target.value)} />
        </>
      ) : null}
      {kind === "suggest" ? (
        <>
          <DepartmentChoice choice={choice} label={T.own.suggestFrom} />
          <SelectField
            label={T.own.target}
            options={targets}
            placeholder={T.inbox.chooseDepartment}
            value={targetOk ? target : ""}
            error={tried && !targetOk ? T.own.chooseTarget : undefined}
            onChange={(e) => setTarget(e.target.value)}
          />
          <TextArea
            label={T.own.reasonRequired}
            maxLength={MAX_REASON}
            value={note}
            error={tried && !note.trim() ? T.own.reasonMissing : undefined}
            onChange={(e) => setNote(e.target.value)}
          />
        </>
      ) : null}
      {kind === "withdraw" ? <p>{T.own.withdrawText}</p> : null}
      {kind === "accept" || kind === "decline" ? (
        <TextArea label={T.own.decideNote} maxLength={MAX_REASON} value={note} onChange={(e) => setNote(e.target.value)} />
      ) : null}
      <ErrorBanner error={run.error} />
      <div className={s.footer}>
        <Button variant="secondary" onClick={onBack}>
          {T.back}
        </Button>
        <span className={s.spacer} />
        <Button type="submit" variant={kind === "decline" || kind === "withdraw" ? "danger" : "primary"} busy={run.busy}>
          {confirmLabel}
        </Button>
      </div>
    </form>
  );
}
