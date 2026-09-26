"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { canWatch, isDeptLead, isOperator } from "@/lib/roles";
import type { CaseCard, Me, Office, User } from "@/lib/types";
import { useOffices } from "../../shell/MeContext";
import { Button } from "../../ui/Button";
import { Dialog, DialogButtons } from "../../ui/Dialog";
import { Field, Select, TextArea } from "../../ui/Field";
import { Notice } from "../../ui/Layout";
import { useToast } from "../../ui/Toast";
import { caseNumber } from "../CaseBits";
import { HandoverDialog } from "./Workflow";

type Open = null | "claim" | "transfer" | "allot" | "release" | "watch" | "handover";

export interface RailPermissions {
  claim: boolean;
  transfer: boolean;
  allot: boolean;
  release: boolean;
  watch: boolean;
  handover: boolean;
  /** Department the caller acts for on an owned case (the owner, for the central operator). */
  actingOfficeId?: string;
}

export function railPermissions(me: Me, c: CaseCard): RailPermissions {
  const primary = c.owners?.primary ?? null;
  const watchers = c.owners?.watchers ?? [];
  const myDept = me.department?.id;
  const operator = isOperator(me);
  const writer = !me.read_only;
  const mineAsPrimary = !!primary && !!myDept && primary.office_id === myDept;
  const mineAsWatcher = !!myDept && watchers.some((w) => w.office_id === myDept);
  const lead = operator || isDeptLead(me);
  return {
    claim: writer && me.can_claim && (operator || (!mineAsPrimary && !mineAsWatcher)),
    transfer: writer && lead && !!primary && (operator || mineAsPrimary),
    allot: writer && lead && !!primary && (operator || mineAsPrimary),
    release: writer && lead && (operator ? !!primary : mineAsPrimary || mineAsWatcher),
    watch: canWatch(me) && !!c.cnr,
    // Hand-over needs access to the case; the backend decides whether the caller holds the file.
    handover: writer && c.in_scope === true,
    actingOfficeId: operator ? (primary?.office_id ?? undefined) : undefined,
  };
}

export function ActionRail({ me, c, onChanged }: { me: Me; c: CaseCard; onChanged: () => void }) {
  const perms = railPermissions(me, c);
  const [open, setOpen] = useState<Open>(null);
  const close = () => setOpen(null);
  const done = () => {
    setOpen(null);
    onChanged();
  };
  if (!perms.claim && !perms.transfer && !perms.allot && !perms.release && !perms.watch && !perms.handover) return null;
  return (
    <>
      {perms.claim ? (
        <Button variant="primary" icon="claim" onClick={() => setOpen("claim")}>
          Claim
        </Button>
      ) : null}
      {perms.handover ? (
        <Button icon="transfer" onClick={() => setOpen("handover")}>
          Hand over
        </Button>
      ) : null}
      {perms.allot ? (
        <Button icon="user" onClick={() => setOpen("allot")}>
          Allot
        </Button>
      ) : null}
      {perms.transfer ? (
        <Button icon="link" onClick={() => setOpen("transfer")}>
          Transfer
        </Button>
      ) : null}
      {perms.watch ? (
        <Button icon="eye" onClick={() => setOpen("watch")}>
          Add to watchlist
        </Button>
      ) : null}
      {perms.release ? (
        <Button variant="danger" onClick={() => setOpen("release")}>
          Release
        </Button>
      ) : null}
      <ClaimDialog open={open === "claim"} me={me} c={c} onClose={close} onDone={done} />
      <TransferDialog open={open === "transfer"} c={c} actingOfficeId={perms.actingOfficeId} onClose={close} onDone={done} />
      <AllotDialog open={open === "allot"} me={me} c={c} actingOfficeId={perms.actingOfficeId} onClose={close} onDone={done} />
      <ReleaseDialog open={open === "release"} c={c} actingOfficeId={perms.actingOfficeId} onClose={close} onDone={done} />
      <HandoverDialog open={open === "handover"} c={c} onClose={close} onDone={done} />
      <WatchDialog open={open === "watch"} me={me} c={c} onClose={close} onDone={done} />
    </>
  );
}

interface DialogProps {
  open: boolean;
  c: CaseCard;
  onClose: () => void;
  onDone: () => void;
}

function DeptSelect({ value, onChange, departments, label, exclude }: { value: string; onChange: (v: string) => void; departments: Office[]; label: string; exclude?: string }) {
  return (
    <Field label={label}>
      <Select value={value} onChange={(e) => onChange(e.target.value)} required data-autofocus>
        <option value="">Choose a department</option>
        {departments
          .filter((d) => d.id !== exclude)
          .map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.code})
            </option>
          ))}
      </Select>
    </Field>
  );
}

function ClaimDialog({ open, me, c, onClose, onDone }: DialogProps & { me: Me }) {
  const { departments } = useOffices();
  const operator = isOperator(me);
  const [office, setOffice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const held = c.owners?.primary;

  const submit = async () => {
    if (operator && !office) return;
    setBusy(true);
    try {
      await api.post(`/cases/${c.id}/claim`, { office_id: operator ? office : null, reason: reason.trim() || null });
      toast.success(`${caseNumber(c)} claimed.`);
      setReason("");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Claim this case"
      description={caseNumber(c)}
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Claim" busy={busy} onCancel={onClose} />}
    >
      {held ? <Notice tone="warning">{held.name} already holds this case. Your department will be recorded as a watcher.</Notice> : null}
      {operator ? <DeptSelect label="Claim for department" value={office} onChange={setOffice} departments={departments} /> : null}
      <Field label="Note (optional)">
        <TextArea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this case belongs to the department" />
      </Field>
    </Dialog>
  );
}

function TransferDialog({ open, c, actingOfficeId, onClose, onDone }: DialogProps & { actingOfficeId?: string }) {
  const { departments } = useOffices();
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const from = c.owners?.primary;

  const submit = async () => {
    if (!to || !reason.trim()) return;
    setBusy(true);
    try {
      await api.post(`/cases/${c.id}/transfer`, { office_id: actingOfficeId ?? null, to_office_id: to, reason: reason.trim() });
      toast.success("Transfer requested. The other department must accept it.");
      setTo("");
      setReason("");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Transfer to another department"
      description={`${caseNumber(c)} stays with ${from?.name ?? "the current owner"} until the other department accepts.`}
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Request transfer" busy={busy} onCancel={onClose} />}
    >
      <DeptSelect label="Transfer to" value={to} onChange={setTo} departments={departments} exclude={from?.office_id} />
      <Field label="Reason (required)">
        <TextArea required value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Dialog>
  );
}

function AllotDialog({ open, me, c, actingOfficeId, onClose, onDone }: DialogProps & { me: Me; actingOfficeId?: string }) {
  const { offices, byId } = useOffices();
  const deptId = actingOfficeId ?? me.department?.id ?? "";
  const dept = byId.get(deptId);
  const units = dept ? offices.filter((o) => o.path.startsWith(`${dept.path}/`) && (o.kind === "directorate" || o.kind === "section")) : [];
  const [unit, setUnit] = useState("");
  const [officer, setOfficer] = useState("");
  const [officers, setOfficers] = useState<User[]>([]);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    const target = unit || deptId;
    if (!target) return;
    let alive = true;
    setOfficer("");
    api
      .get<User[]>(`/offices/${target}/officers`)
      .then((u) => {
        if (alive) setOfficers(u);
      })
      .catch(() => {
        if (alive) setOfficers([]);
      });
    return () => {
      alive = false;
    };
  }, [open, unit, deptId]);

  const submit = async () => {
    if (!unit && !officer) return;
    setBusy(true);
    try {
      await api.post(`/cases/${c.id}/allot`, {
        office_id: actingOfficeId ?? null,
        unit_office_id: unit || null,
        officer_user_id: officer || null,
      });
      toast.success("Case allotted.");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Allot within the department"
      description="Allot the case to a unit (directorate or section), an officer, or both. They will see it and receive its alerts."
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Allot" busy={busy} onCancel={onClose} />}
    >
      <Field label="Unit">
        <Select value={unit} onChange={(e) => setUnit(e.target.value)} data-autofocus>
          <option value="">Department level (no unit)</option>
          {units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.code})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Officer">
        <Select value={officer} onChange={(e) => setOfficer(e.target.value)}>
          <option value="">No particular officer</option>
          {officers.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
              {u.designation ? `, ${u.designation}` : ""}
            </option>
          ))}
        </Select>
      </Field>
    </Dialog>
  );
}

function ReleaseDialog({ open, c, actingOfficeId, onClose, onDone }: DialogProps & { actingOfficeId?: string }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await api.post(`/cases/${c.id}/release`, { office_id: actingOfficeId ?? null, reason: reason.trim() });
      toast.success("Released. The case returns to the unclaimed pool unless another department holds it.");
      setReason("");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Release this case"
      description={`Your department stops holding ${caseNumber(c)}. The court record stays in the portal.`}
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Release" busy={busy} onCancel={onClose} danger />}
    >
      <Field label="Reason (required)">
        <TextArea required value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Dialog>
  );
}

function WatchDialog({ open, me, c, onClose, onDone }: DialogProps & { me: Me }) {
  const { departments } = useOffices();
  const operator = isOperator(me);
  const [office, setOffice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async () => {
    if (!c.cnr || (operator && !office)) return;
    setBusy(true);
    try {
      await api.post("/mapping/watchlist", { office_id: operator ? office : null, cnr: c.cnr, reason: reason.trim() || null });
      toast.success("Added to the department watchlist. It now counts towards recommendations.");
      setReason("");
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add to the department watchlist"
      description={`CNR ${c.cnr ?? ""}. A watchlisted case is recommended to the department whenever it is listed.`}
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Add to watchlist" busy={busy} onCancel={onClose} />}
    >
      {operator ? <DeptSelect label="Department" value={office} onChange={setOffice} departments={departments} /> : null}
      <Field label="Reason (optional)">
        <TextArea value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Dialog>
  );
}
