"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { daysUntil, fmtDate, fmtDateTime, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { REQUEST_KINDS, requestKindLabel, requestStatusLabel } from "@/lib/labels";
import type { RequestOut } from "@/lib/types";
import { Button } from "../../ui/Button";
import { Dialog, DialogButtons } from "../../ui/Dialog";
import { Field, FormRow, Select, TextArea, TextInput } from "../../ui/Field";
import { Card } from "../../ui/Layout";
import { Pill } from "../../ui/Pill";
import { Async, Empty } from "../../ui/States";
import { useToast } from "../../ui/Toast";
import s from "./detail.module.css";
import { OfficeOfficerPicker } from "./Workflow";

export function RequestStatusPill({ r }: { r: RequestOut }) {
  if (r.status === "answered") return <Pill tone="success">Answered</Pill>;
  if (r.status === "withdrawn") return <Pill tone="muted">Withdrawn</Pill>;
  return <Pill tone="info">{requestStatusLabel(r.status)}</Pill>;
}

export function DuePill({ r }: { r: RequestOut }) {
  if (!r.due_date || r.status !== "open") return null;
  if (r.overdue) return <Pill tone="critical">Overdue · due {fmtDate(r.due_date)}</Pill>;
  const d = daysUntil(r.due_date);
  if (d !== null && d <= 2) return <Pill tone="criticalSoft">Due {fmtDate(r.due_date)}</Pill>;
  if (d !== null && d <= 7) return <Pill tone="warning">Due {fmtDate(r.due_date)}</Pill>;
  return <Pill tone="muted">Due {fmtDate(r.due_date)}</Pill>;
}

type Mode = null | "answer" | "reply" | "withdraw";

/** One request with its message thread and the Answer / Reply / Withdraw actions (the backend decides who may act). */
export function RequestCard({ r, canAct, onChanged, showCase }: { r: RequestOut; canAct: boolean; onChanged: () => void; showCase?: boolean }) {
  const toast = useToast();
  const [mode, setMode] = useState<Mode>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!mode) return;
    if (mode !== "withdraw" && !text.trim()) return;
    setBusy(true);
    try {
      if (mode === "answer") await api.post(`/requests/${r.id}/answer`, { body: text.trim() });
      else if (mode === "reply") await api.post(`/requests/${r.id}/messages`, { body: text.trim() });
      else await api.post(`/requests/${r.id}/withdraw`, { reason: text.trim() || null });
      toast.success(mode === "answer" ? "Request answered." : mode === "reply" ? "Reply sent." : "Request withdrawn.");
      setMode(null);
      setText("");
      onChanged();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  const open = r.status === "open";
  return (
    <Card as="article">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <RequestStatusPill r={r} />
        <DuePill r={r} />
        <Pill tone="neutral">{requestKindLabel(r.kind)}</Pill>
        <span className="mono muted" style={{ fontSize: 12 }} title="Request reference number">
          {r.ref_no}
        </span>
        {showCase ? (
          <Link href={`/cases/${r.case_id}?tab=requests`} className="mono" style={{ fontSize: 13, fontWeight: 500 }}>
            {r.case_no ?? "Open case"}
          </Link>
        ) : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <strong style={{ fontSize: 16 }}>{r.subject}</strong>
        <span className="muted" style={{ fontSize: 13 }}>
          {r.from_office.name} to {r.to_office.name}
          {r.to_user ? ` (${r.to_user})` : ""} · sent {fmtDateTime(r.created_at)}
          {r.requested_by ? ` by ${r.requested_by}` : ""}
          {r.answered_at ? ` · answered ${fmtDateTime(r.answered_at)}` : ""}
        </span>
        {r.body ? <p style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{r.body}</p> : null}
      </div>
      {r.messages && r.messages.length ? (
        <div className={s.thread} aria-label="Messages">
          {r.messages.map((m) => (
            <div key={m.id} className={`${s.msg} ${m.is_answer ? s.msgAnswer : ""}`}>
              <span className={s.msgMeta}>
                {m.is_answer ? "Answer · " : ""}
                {m.author ?? "Unknown"}
                {m.author_office ? ` (${m.author_office})` : ""} · {fmtDateTime(m.created_at)}
              </span>
              <span style={{ whiteSpace: "pre-wrap" }}>{m.body}</span>
            </div>
          ))}
        </div>
      ) : null}
      {canAct ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {open ? (
            <Button small variant="primary" onClick={() => setMode("answer")}>
              Answer
            </Button>
          ) : null}
          <Button small onClick={() => setMode("reply")}>
            Reply
          </Button>
          {open ? (
            <Button small variant="danger" onClick={() => setMode("withdraw")}>
              Withdraw
            </Button>
          ) : null}
        </div>
      ) : null}
      <Dialog
        open={mode !== null}
        onClose={() => setMode(null)}
        title={mode === "answer" ? "Answer the request" : mode === "reply" ? "Reply" : "Withdraw the request"}
        description={r.subject}
        onSubmit={submit}
        footer={
          <DialogButtons
            submitLabel={mode === "answer" ? "Send answer" : mode === "reply" ? "Send reply" : "Withdraw"}
            busy={busy}
            danger={mode === "withdraw"}
            onCancel={() => setMode(null)}
          />
        }
      >
        <Field label={mode === "withdraw" ? "Reason (optional)" : mode === "answer" ? "Answer" : "Message"}>
          <TextArea required={mode !== "withdraw"} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}

function NewRequestDialog({ open, caseId, onClose, onDone }: { open: boolean; caseId: string; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const blank = { kind: "report", office: "", user: "", subject: "", body: "", due: "" };
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!f.office || !f.subject.trim()) return;
    setBusy(true);
    try {
      await api.post(`/cases/${caseId}/requests`, {
        kind: f.kind,
        to_office_id: f.office,
        to_user_id: f.user || null,
        subject: f.subject.trim(),
        body: f.body.trim() || null,
        due_date: f.due || null,
      });
      toast.success("Request sent. The file moves to the receiving office until it answers.");
      setF(blank);
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} wide title="New request" onSubmit={submit} footer={<DialogButtons submitLabel="Send request" busy={busy} onCancel={onClose} />}>
      <Field label="Kind">
        <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {REQUEST_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </Select>
      </Field>
      <OfficeOfficerPicker officeId={f.office} userId={f.user} onOffice={(v) => setF((x) => ({ ...x, office: v }))} onUser={(v) => setF((x) => ({ ...x, user: v }))} />
      <Field label="Subject">
        <TextInput required value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} maxLength={300} />
      </Field>
      <Field label="Details (optional)">
        <TextArea value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
      </Field>
      <FormRow>
        <Field label="Due date (optional)">
          <TextInput type="date" min={todayIST()} value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
        </Field>
      </FormRow>
    </Dialog>
  );
}

export function RequestsTab({ caseId, canWrite, onChanged }: { caseId: string; canWrite: boolean; onChanged: () => void }) {
  const state = useApi<RequestOut[]>(`/cases/${caseId}/requests`);
  const [creating, setCreating] = useState(false);
  const changed = () => {
    state.reload();
    onChanged();
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <p className="muted" style={{ fontSize: 14, maxWidth: 680 }}>
          Ask another office for records, a report, instructions or views. The file moves to that office until the request is answered or withdrawn.
        </p>
        {canWrite ? (
          <Button variant="primary" onClick={() => setCreating(true)}>
            New request
          </Button>
        ) : null}
      </div>
      <Async state={state} loadingLabel="Loading requests">
        {(rows) =>
          rows.length === 0 ? (
            <Empty title="No requests on this case" />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {rows.map((r) => (
                <RequestCard key={r.id} r={r} canAct={canWrite} onChanged={changed} />
              ))}
            </div>
          )
        }
      </Async>
      {canWrite ? (
        <NewRequestDialog
          open={creating}
          caseId={caseId}
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            changed();
          }}
        />
      ) : null}
    </div>
  );
}
