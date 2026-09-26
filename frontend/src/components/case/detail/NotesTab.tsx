"use client";

import { useRef, useState, type FormEvent } from "react";
import { api, apiUrl } from "@/lib/api";
import { describeTypes, useConfig } from "@/lib/config";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { NOTE_KINDS, noteKindLabel, scanLabel, VISIBILITY, visibilityLabel } from "@/lib/labels";
import { roleLabel } from "@/lib/roles";
import type { CustodyLeg, Note } from "@/lib/types";
import { Button } from "../../ui/Button";
import { Field, Fieldset, FormRow, Radio, Select, TextArea } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { Card, Notice } from "../../ui/Layout";
import { Pill } from "../../ui/Pill";
import { Async, Empty } from "../../ui/States";
import { useToast } from "../../ui/Toast";
import s from "./detail.module.css";
import { fmtLegHeading } from "./Workflow";

function NoteView({ n, canWrite, onCorrect }: { n: Note; canWrite: boolean; onCorrect: (n: Note) => void }) {
  const superseded = n.superseded_by.length > 0;
  return (
    <article className={`${s.note} ${superseded ? s.noteSuperseded : ""}`} id={`note-${n.seq_no}`} aria-label={`Note ${n.seq_no}`}>
      <div className={s.noteHead}>
        <span className={s.noteNo}>Note {n.seq_no}</span>
        <Pill tone="neutral">{noteKindLabel(n.kind)}</Pill>
        <Pill tone={n.visibility === "case_scope" ? "muted" : "warning"}>{visibilityLabel(n.visibility)}</Pill>
        {n.supersedes_seq ? (
          <a href={`#note-${n.supersedes_seq}`} style={{ fontSize: 13, fontWeight: 600 }}>
            Corrects Note {n.supersedes_seq}
          </a>
        ) : null}
        {superseded ? (
          <Pill tone="criticalSoft">
            Corrected by {n.superseded_by.map((x) => `Note ${x}`).join(", ")}
          </Pill>
        ) : null}
        {n.source && n.source !== "manual" ? <Pill tone="infoSoft">{n.source === "assistant" ? "From Case Assistant" : n.source}</Pill> : null}
      </div>
      <div className={s.noteAuthor}>
        {n.author ?? "Unknown author"}
        {n.author_designation ? `, ${n.author_designation}` : ""}
        {n.author_office ? ` · ${n.author_office}` : ""} · {roleLabel(n.author_role)} · {fmtDateTime(n.created_at)}
      </div>
      <div className={s.noteBody}>{n.body}</div>
      {n.attachments && n.attachments.length ? (
        <div className={s.attachments}>
          {n.attachments.map((a) => {
            const ok = a.virus_scan_status === "clean" || a.virus_scan_status === "not_applicable";
            return ok ? (
              <a key={a.document_id} href={apiUrl(`/documents/${a.document_id}/download`)} target="_blank" rel="noopener" className={s.attachment}>
                <Icon name="file" size={14} />
                {a.filename ?? "Attachment"} · {fmtBytes(a.size_bytes)}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <span key={a.document_id} className={s.attachment} style={{ color: "var(--muted)" }}>
                <Icon name="file" size={14} />
                {a.filename ?? "Attachment"} · {scanLabel(a.virus_scan_status)}
              </span>
            );
          })}
        </div>
      ) : null}
      {canWrite && !superseded ? (
        <div>
          <Button variant="link" small onClick={() => onCorrect(n)}>
            Correct this note<span className="sr-only"> (Note {n.seq_no})</span>
          </Button>
        </div>
      ) : null}
    </article>
  );
}

function Composer({ caseId, correcting, onCancelCorrect, onSaved }: { caseId: string; correcting: Note | null; onCancelCorrect: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { config } = useConfig();
  const exts = config.allowed_upload_types.map((e) => e.toLowerCase());
  const [body, setBody] = useState("");
  const [kind, setKind] = useState("general");
  const [visibility, setVisibility] = useState("case_scope");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const pick = (list: FileList | null) => {
    setError(null);
    const chosen = Array.from(list ?? []);
    for (const f of chosen) {
      const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
      if (!exts.includes(ext)) {
        setError(`${f.name}: only ${describeTypes(exts)} files can be attached.`);
        return;
      }
      if (f.size > config.upload_max_mb * 1024 * 1024) {
        setError(`${f.name} is larger than ${config.upload_max_mb} MB.`);
        return;
      }
    }
    setFiles(chosen);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    const form = new FormData();
    form.append("body", body.trim());
    form.append("kind", kind);
    form.append("visibility", visibility);
    if (correcting) form.append("supersedes_id", correcting.id);
    for (const f of files) form.append("files", f);
    setBusy(true);
    try {
      const n = await api.upload<Note>(`/cases/${caseId}/notes`, form);
      toast.success(correcting ? `Note ${n.seq_no} added; it corrects Note ${correcting.seq_no}.` : `Note ${n.seq_no} added.`);
      setBody("");
      setFiles([]);
      if (input.current) input.current.value = "";
      onSaved();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card as="section" labelledBy="composer-h" className={s.side}>
      <h2 id="composer-h">{correcting ? `Correct Note ${correcting.seq_no}` : "Add a note"}</h2>
      <Notice>
        <Icon name="lock" size={16} />
        Notes cannot be edited or deleted. A correction is a new note that points to the old one; both stay in the trail.
      </Notice>
      {correcting ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
          <Pill tone="warning">Correcting Note {correcting.seq_no}</Pill>
          <Button variant="link" small onClick={onCancelCorrect}>
            Cancel correction
          </Button>
        </div>
      ) : null}
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label="Note">
          <TextArea id="note-body" required rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <FormRow>
          <Field label="Kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {NOTE_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </Field>
        </FormRow>
        <Fieldset legend="Who can see it">
          {VISIBILITY.map((v) => (
            <Radio key={v.value} name="note-visibility" value={v.value} checked={visibility === v.value} onChange={() => setVisibility(v.value)} label={v.label} />
          ))}
        </Fieldset>
        <Field label="Attachments (optional)" hint={`${describeTypes(exts)}, up to ${config.upload_max_mb} MB each; checked for viruses. Never sent to SourceTrace.`}>
          <input ref={input} type="file" multiple accept={exts.join(",")} onChange={(e) => pick(e.target.files)} style={{ fontSize: 14, minHeight: 44 }} />
        </Field>
        {files.length ? <div className="muted" style={{ fontSize: 13 }}>{files.map((f) => `${f.name} (${fmtBytes(f.size)})`).join(", ")}</div> : null}
        {error ? (
          <div role="alert" style={{ color: "var(--critical)", fontSize: 13 }}>
            {error}
          </div>
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={busy}>
            {correcting ? "Add correcting note" : "Add note"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

/** The append-only noting trail, grouped by custody leg as on the boards. */
export function NotesTab({ caseId, canWrite }: { caseId: string; canWrite: boolean }) {
  const notes = useApi<Note[]>(`/cases/${caseId}/notes`);
  const legs = useApi<CustodyLeg[]>(`/cases/${caseId}/custody/history`);
  const [correcting, setCorrecting] = useState<Note | null>(null);

  const correct = (n: Note) => {
    setCorrecting(n);
    window.setTimeout(() => document.getElementById("note-body")?.focus(), 0);
  };

  return (
    <div className={s.columns}>
      <div className={s.main}>
        <Async state={notes} loadingLabel="Loading the notes trail">
          {(list) => {
            if (list.length === 0) return <Card><Empty title="No notes yet">The noting trail follows the case across offices.</Empty></Card>;
            const sorted = [...list].sort((a, b) => a.seq_no - b.seq_no);
            const groups: { leg: number | null; notes: Note[] }[] = [];
            for (const n of sorted) {
              const last = groups[groups.length - 1];
              if (last && last.leg === n.custody_leg_seq) last.notes.push(n);
              else groups.push({ leg: n.custody_leg_seq, notes: [n] });
            }
            return (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                {groups.map((g, i) => (
                  <section key={`${g.leg}-${i}`} className={s.legGroup} aria-label={fmtLegHeading(g.leg, legs.data ?? [])}>
                    <div className={s.legHead}>
                      <strong>{fmtLegHeading(g.leg, legs.data ?? [])}</strong>
                      <span className="muted">
                        {g.notes.length} {g.notes.length === 1 ? "note" : "notes"}
                      </span>
                    </div>
                    {g.notes.map((n) => (
                      <NoteView key={n.id} n={n} canWrite={canWrite} onCorrect={correct} />
                    ))}
                  </section>
                ))}
              </div>
            );
          }}
        </Async>
      </div>
      {canWrite ? (
        <Composer
          caseId={caseId}
          correcting={correcting}
          onCancelCorrect={() => setCorrecting(null)}
          onSaved={() => {
            setCorrecting(null);
            notes.reload();
          }}
        />
      ) : null}
    </div>
  );
}
