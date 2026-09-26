"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate, fmtDateTime, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { custodyReasonLabel, stageLabel } from "@/lib/labels";
import type { CaseCard, CustodyLeg, Note, Office, StageOut, StageSet, User } from "@/lib/types";
import { useOffices } from "../../shell/MeContext";
import { Button } from "../../ui/Button";
import { Dialog, DialogButtons } from "../../ui/Dialog";
import { Field, FormRow, Radio, Fieldset, Select, TextArea, TextInput } from "../../ui/Field";
import { Card, CardHead, Notice } from "../../ui/Layout";
import { Pill } from "../../ui/Pill";
import { Async, Empty } from "../../ui/States";
import { useToast } from "../../ui/Toast";
import { depth } from "../../admin/common";
import s from "./detail.module.css";
import { Timeline } from "./Timeline";

/** "With <holder> since <date> · N days · pending: <action> · due <date>" plus the current stage. */
export function CustodyStrip({ c }: { c: CaseCard }) {
  const k = c.custody;
  if (!k && !c.stage) return null;
  return (
    <div className={`${s.strip} ${k?.overdue ? s.stripOverdue : ""}`} role="status" aria-label="Custody and stage">
      {k ? (
        <>
          <span className={s.stripLabel}>Custody</span>
          <span>
            With <strong>{k.holder_office.name}</strong>
            {k.holder_user ? ` (${k.holder_user})` : ""} since {fmtDate(k.since)}
          </span>
          <span>
            · {k.days_pending} {k.days_pending === 1 ? "day" : "days"}
          </span>
          {k.pending_action ? <span>· pending: {k.pending_action}</span> : null}
          {k.due_date ? (
            <span className={s.stripDue}>
              · due {fmtDate(k.due_date)}
              {k.overdue ? " (overdue)" : ""}
            </span>
          ) : k.overdue ? (
            <span className={s.stripDue}>· overdue</span>
          ) : null}
        </>
      ) : (
        <span className="muted">No custody recorded yet</span>
      )}
      {c.stage ? (
        <span style={{ marginLeft: "auto" }}>
          <Pill tone="info">Stage: {stageLabel(c.stage)}</Pill>
        </span>
      ) : null}
    </div>
  );
}

/** The movement trail: every custody leg, newest first. Public, like the tracking card. */
export function CustodyTrail({ caseId, title = "Movement trail" }: { caseId: string; title?: string }) {
  const state = useApi<CustodyLeg[]>(`/cases/${caseId}/custody/history`);
  return (
    <Card labelledBy={`trail-${caseId}`}>
      <CardHead id={`trail-${caseId}`} title={title} caption />
      <Async state={state} loadingLabel="Loading the movement trail">
        {(legs) =>
          legs.length === 0 ? (
            <Empty title="The file has not moved yet" />
          ) : (
            <Timeline
              entries={[...legs]
                .sort((a, b) => b.seq_no - a.seq_no)
                .map((l) => ({
                  key: String(l.seq_no),
                  date: l.started_at,
                  title: `${l.seq_no}. ${l.holder_office}${l.holder_user ? ` · ${l.holder_user}` : ""}`,
                  text:
                    [
                      custodyReasonLabel(l.reason),
                      l.pending_action ? `pending: ${l.pending_action}` : null,
                      l.due_date ? `due ${fmtDate(l.due_date)}` : null,
                      l.moved_by ? `moved by ${l.moved_by}${l.moved_by_office ? ` (${l.moved_by_office})` : ""}` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || undefined,
                }))}
            />
          )
        }
      </Async>
    </Card>
  );
}

/** Office then officer. The officer list is limited by the backend to offices you may see. */
export function OfficeOfficerPicker({
  officeId,
  userId,
  onOffice,
  onUser,
  officeLabel = "To office",
}: {
  officeId: string;
  userId: string;
  onOffice: (v: string) => void;
  onUser: (v: string) => void;
  officeLabel?: string;
}) {
  const { offices } = useOffices();
  const [officers, setOfficers] = useState<User[] | null>(null);
  const active = offices.filter((o: Office) => o.is_active);
  useEffect(() => {
    if (!officeId) {
      setOfficers(null);
      return;
    }
    let alive = true;
    api
      .get<User[]>(`/offices/${officeId}/officers`)
      .then((u) => alive && setOfficers(u))
      .catch(() => alive && setOfficers([]));
    return () => {
      alive = false;
    };
  }, [officeId]);
  return (
    <FormRow>
      <Field label={officeLabel}>
        <Select
          value={officeId}
          required
          data-autofocus
          onChange={(e) => {
            onOffice(e.target.value);
            onUser("");
          }}
        >
          <option value="">Choose an office</option>
          {active.map((o) => (
            <option key={o.id} value={o.id}>
              {"  ".repeat(depth(o))}
              {o.name} ({o.code})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Officer (optional)" hint={officers && officers.length === 0 && officeId ? "No officers listed for this office." : undefined}>
        <Select value={userId} onChange={(e) => onUser(e.target.value)} disabled={!officeId}>
          <option value="">Anyone in the office</option>
          {(officers ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
              {u.designation ? `, ${u.designation}` : ""}
            </option>
          ))}
        </Select>
      </Field>
    </FormRow>
  );
}

/** Hand-over: writes a hand-over note and moves custody in one step. */
export function HandoverDialog({ open, c, onClose, onDone }: { open: boolean; c: CaseCard; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [office, setOffice] = useState("");
  const [user, setUser] = useState("");
  const [note, setNote] = useState("");
  const [action, setAction] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!office || !note.trim()) return;
    setBusy(true);
    try {
      const n = await api.post<Note>(`/cases/${c.id}/handover`, {
        to_office_id: office,
        to_user_id: user || null,
        note: note.trim(),
        pending_action: action.trim() || null,
        due_date: due || null,
      });
      toast.success(`Handed over. Recorded as Note ${n.seq_no}.`);
      setOffice("");
      setUser("");
      setNote("");
      setAction("");
      setDue("");
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
      wide
      title="Hand over the file"
      description="Writes a hand-over note to the notes trail and moves custody to the office you choose, in one step."
      onSubmit={submit}
      footer={<DialogButtons submitLabel="Hand over" busy={busy} onCancel={onClose} />}
    >
      <OfficeOfficerPicker officeId={office} userId={user} onOffice={setOffice} onUser={setUser} />
      <Field label="Hand-over note (required)">
        <TextArea required value={note} onChange={(e) => setNote(e.target.value)} placeholder="What the receiving office needs to know" />
      </Field>
      <FormRow>
        <Field label="Pending action (optional)">
          <TextInput value={action} onChange={(e) => setAction(e.target.value)} placeholder="e.g. prepare parawise comments" />
        </Field>
        <Field label="Due date (optional)">
          <TextInput type="date" min={todayIST()} value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>
      </FormRow>
    </Dialog>
  );
}

const SIDE_TRACK_FROM = "appeal_review_under_consideration";

/** Lifecycle stepper with the stage history. Guided, not enforced: any stage can be set; gaps are shown. */
export function StageCard({ c, canSet, onChanged }: { c: CaseCard; canSet: boolean; onChanged: () => void }) {
  const toast = useToast();
  const stages = useApi<string[]>("/stages");
  const history = useApi<StageOut[]>(`/cases/${c.id}/stages`);
  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState("");
  const [note, setNote] = useState("");
  const [mode, setMode] = useState("");
  const [busy, setBusy] = useState(false);
  const [skipped, setSkipped] = useState<string[]>([]);

  const all = stages.data ?? [];
  const cut = all.indexOf(SIDE_TRACK_FROM);
  const main = cut > 0 ? all.slice(0, cut) : all;
  const side = cut > 0 ? all.slice(cut) : [];
  const current = c.stage ?? history.data?.[0]?.stage ?? null;
  const currentIdx = current ? main.indexOf(current) : -1;
  const recorded = new Set((history.data ?? []).map((h) => h.stage));
  // Main-track stages before the current one that were never recorded: the gap, derived from the history.
  const gaps = history.data && currentIdx > 0 ? main.slice(0, currentIdx).filter((st) => !recorded.has(st)) : [];
  const shownGaps = skipped.length ? skipped : gaps;

  const submit = async () => {
    if (!stage) return;
    setBusy(true);
    try {
      const res = await api.post<StageSet>(`/cases/${c.id}/stages`, {
        stage,
        note: note.trim() || null,
        response_mode: stage === "response_mode_decided" && mode ? mode : null,
      });
      setSkipped(res.skipped ?? []);
      toast.success(`Stage set to ${stageLabel(res.stage)}.`);
      setOpen(false);
      setNote("");
      setMode("");
      history.reload();
      onChanged();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card labelledBy="stage-h">
      <CardHead
        id="stage-h"
        title="Lifecycle stage"
        caption
        actions={
          canSet ? (
            <Button
              small
              onClick={() => {
                setStage(current ?? main[0] ?? "");
                setOpen(true);
              }}
            >
              Set stage
            </Button>
          ) : null
        }
      />
      {main.length ? (
        <ol className={s.stepper} aria-label="Main track">
          {main.map((st, i) => (
            <li
              key={st}
              className={`${s.step} ${i === currentIdx ? s.stepCurrent : i < currentIdx ? (recorded.has(st) ? s.stepDone : s.stepGap) : ""}`}
              aria-current={i === currentIdx ? "step" : undefined}
            >
              <span className={s.stepNo}>{i + 1}</span>
              {stageLabel(st)}
              {i < currentIdx && !recorded.has(st) ? <span className="sr-only"> (not recorded)</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {current && main.indexOf(current) < 0 ? (
        <div>
          <Pill tone="info">Current: {stageLabel(current)}</Pill>
        </div>
      ) : null}
      {!current ? <p className="muted" style={{ fontSize: 13 }}>No stage recorded yet.</p> : null}
      {shownGaps.length ? (
        <Notice tone="warning">
          Gap on the main track: {shownGaps.map(stageLabel).join(", ")} {shownGaps.length === 1 ? "was" : "were"} skipped. This is allowed; record{" "}
          {shownGaps.length === 1 ? "it" : "them"} if {shownGaps.length === 1 ? "it" : "they"} happened.
        </Notice>
      ) : null}
      {history.data && history.data.length ? (
        <details>
          <summary style={{ cursor: "pointer", color: "var(--accent)", fontWeight: 600, fontSize: 13, minHeight: 32 }}>Stage history ({history.data.length})</summary>
          <Timeline
            entries={history.data.map((h) => ({
              key: h.id,
              date: h.created_at,
              title: `${stageLabel(h.stage)}${h.response_mode ? ` (${h.response_mode === "dept_led" ? "department-led" : "directorate-led"})` : ""}`,
              text: [h.note, h.set_by ? `set by ${h.set_by}${h.set_by_office ? ` (${h.set_by_office})` : ""}` : null].filter(Boolean).join(" · ") || undefined,
            }))}
          />
        </details>
      ) : null}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Set the lifecycle stage"
        description="Guided, not enforced. Stages jumped over on the main track are shown as a gap."
        onSubmit={submit}
        footer={<DialogButtons submitLabel="Set stage" busy={busy} onCancel={() => setOpen(false)} />}
      >
        <Field label="Stage">
          <Select value={stage} onChange={(e) => setStage(e.target.value)} required data-autofocus>
            <optgroup label="Main track">
              {main.map((st) => (
                <option key={st} value={st}>
                  {stageLabel(st)}
                </option>
              ))}
            </optgroup>
            {side.length ? (
              <optgroup label="Appeal, contempt and counsel">
                {side.map((st) => (
                  <option key={st} value={st}>
                    {stageLabel(st)}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </Select>
        </Field>
        {stage === "response_mode_decided" ? (
          <Fieldset legend="Response led by">
            <Radio name="mode" label="The department" checked={mode === "dept_led"} onChange={() => setMode("dept_led")} />
            <Radio name="mode" label="The directorate" checked={mode === "directorate_led"} onChange={() => setMode("directorate_led")} />
          </Fieldset>
        ) : null}
        <Field label="Note (optional)">
          <TextArea value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}

export function fmtLegHeading(seq: number | null, legs: CustodyLeg[]): string {
  if (seq === null) return "Before custody was recorded";
  const leg = legs.find((l) => l.seq_no === seq);
  if (!leg) return `Custody leg ${seq}`;
  return `Leg ${seq} · with ${leg.holder_office}${leg.holder_user ? ` (${leg.holder_user})` : ""} from ${fmtDateTime(leg.started_at)}`;
}
