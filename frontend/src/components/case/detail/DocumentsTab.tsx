"use client";

import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { api, apiUrl } from "@/lib/api";
import { describeTypes, useConfig } from "@/lib/config";
import { fmtBytes, fmtDate, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { docTypeLabel, scanLabel, sourceTraceLabel, UPLOAD_DOC_TYPES, VISIBILITY, visibilityLabel } from "@/lib/labels";
import type { DocumentOut } from "@/lib/types";
import { Button } from "../../ui/Button";
import { Check, Field, Fieldset, Radio, Select, TextInput } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { Card, Notice } from "../../ui/Layout";
import { Pill, type Tone } from "../../ui/Pill";
import { Async, Empty } from "../../ui/States";
import { useToast } from "../../ui/Toast";
import s from "./detail.module.css";


const GROUPS: { id: string; title: string; note: string }[] = [
  { id: "court_record", title: "Court orders", note: "Collected automatically" },
  { id: "court_filing", title: "Court filings", note: "May be read by the Case Assistant" },
  { id: "internal", title: "Internal documents", note: "Never sent to SourceTrace" },
];

function mimeShort(mime: string): string {
  if (mime === "application/pdf") return "PDF";
  if (mime.includes("word")) return "Word";
  if (mime.startsWith("image/")) return mime.slice(6).toUpperCase();
  return mime;
}

function stTone(v: string): Tone {
  if (v === "ingested") return "success";
  if (v === "failed") return "criticalSoft";
  if (v === "pending") return "warning";
  return "muted";
}

function scanTone(v: string): Tone {
  if (v === "infected" || v === "failed") return "criticalSoft";
  if (v === "pending") return "warning";
  return "success";
}

function DocRow({ d }: { d: DocumentOut }) {
  const downloadable = d.virus_scan_status === "clean" || d.virus_scan_status === "not_applicable";
  const title = d.description || docTypeLabel(d.doc_type);
  return (
    <div className={s.docRow}>
      <div className={s.docIcon} aria-hidden="true">
        <Icon name="file" />
      </div>
      <div className={s.docText}>
        <div className={s.docTitle}>
          {downloadable ? (
            <a href={apiUrl(`/documents/${d.id}/download`)} target="_blank" rel="noopener">
              {title}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            title
          )}
        </div>
        <div className={s.docMeta}>
          {docTypeLabel(d.doc_type)}
          {d.doc_date ? ` dated ${fmtDate(d.doc_date)}` : ""} · {d.actor_name ? `Uploaded ${fmtDate(d.created_at)} by ${d.actor_name}` : `Added ${fmtDate(d.created_at)}`}
          {d.actor_office_code ? ` (${d.actor_office_code})` : ""} · {mimeShort(d.mime)}, {fmtBytes(d.size_bytes)}
        </div>
      </div>
      <div className={s.docPills}>
        {d.virus_scan_status !== "clean" && d.virus_scan_status !== "not_applicable" ? (
          <Pill tone={scanTone(d.virus_scan_status)}>{scanLabel(d.virus_scan_status)}</Pill>
        ) : null}
        <Pill tone={stTone(d.sourcetrace_status)}>{sourceTraceLabel(d.sourcetrace_status)}</Pill>
        {d.doc_group !== "court_record" ? (
          <Pill tone={d.visibility === "case_scope" ? "muted" : "warning"}>{visibilityLabel(d.visibility)}</Pill>
        ) : null}
      </div>
    </div>
  );
}

function UploadPanel({ caseId, onUploaded }: { caseId: string; onUploaded: () => void }) {
  const toast = useToast();
  const { config } = useConfig();
  const EXTENSIONS = config.allowed_upload_types.map((e) => e.toLowerCase());
  const ACCEPT = EXTENSIONS.join(",");
  const MAX_MB = config.upload_max_mb;
  const kinds = describeTypes(EXTENSIONS);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [docType, setDocType] = useState("affidavit_in_opposition");
  const [docDate, setDocDate] = useState(todayIST());
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("case_scope");
  const [otherInternal, setOtherInternal] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const typeDef = UPLOAD_DOC_TYPES.find((t) => t.value === docType);
  const internal = docType === "other" ? otherInternal : typeDef?.group === "internal";

  const pick = (f: File | null | undefined) => {
    setError(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXTENSIONS.includes(ext)) {
      setError(`Only ${kinds} files can be uploaded (${EXTENSIONS.join(", ")}).`);
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`The file is larger than ${MAX_MB} MB.`);
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const reset = () => {
    setFile(null);
    setDescription("");
    setError(null);
    if (input.current) input.current.value = "";
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Choose a file to upload.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    form.append("visibility", visibility);
    if (docDate) form.append("doc_date", docDate);
    if (description.trim()) form.append("description", description.trim());
    if (docType === "other") form.append("internal", otherInternal ? "true" : "false");
    setBusy(true);
    try {
      const doc = await api.upload<DocumentOut>(`/cases/${caseId}/documents`, form);
      toast.success(
        doc.virus_scan_status === "clean" || doc.virus_scan_status === "not_applicable"
          ? "Document uploaded."
          : `Document uploaded. ${scanLabel(doc.virus_scan_status)}.`,
      );
      reset();
      onUploaded();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card as="section" labelledBy="upload-h" className={s.side}>
      <h2 id="upload-h">Upload a document</h2>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <label
          className={`${s.dropzone} ${drag ? s.dropActive : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
        >
          <span className={s.dropIcon} aria-hidden="true">
            <Icon name="upload" />
          </span>
          <span className={s.dropTitle}>{file ? file.name : "Drop a file here or choose a file"}</span>
          <span>{file ? fmtBytes(file.size) : `${kinds}, up to ${MAX_MB} MB · checked for viruses before saving`}</span>
          <input ref={input} type="file" accept={ACCEPT} className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
        </label>
        {error ? (
          <div role="alert" style={{ color: "var(--critical)", fontSize: 13 }}>
            {error}
          </div>
        ) : null}
        <Field label="Document type">
          <Select value={docType} onChange={(e) => setDocType(e.target.value)}>
            {UPLOAD_DOC_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </Field>
        {docType === "other" ? (
          <Check label="Internal document (never sent to SourceTrace)" checked={otherInternal} onChange={(e) => setOtherInternal(e.target.checked)} />
        ) : null}
        <Notice tone={internal ? "warning" : "info"}>
          <Icon name={internal ? "lock" : "info"} size={16} />
          {internal
            ? "Internal document · stays in the portal, never sent to SourceTrace"
            : config.sourcetrace_enabled
              ? "Court filing · will be available to the Case Assistant"
              : "Court filing · will reach the Case Assistant once SourceTrace is connected"}
        </Notice>
        <Field label="Document date">
          <TextInput type="date" value={docDate} max={todayIST()} onChange={(e) => setDocDate(e.target.value)} />
        </Field>
        <Field label="Description">
          <TextInput value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Short description" maxLength={300} />
        </Field>
        <Fieldset legend="Who can see it">
          {VISIBILITY.map((v) => (
            <Radio key={v.value} name="visibility" value={v.value} checked={visibility === v.value} onChange={() => setVisibility(v.value)} label={v.label} />
          ))}
        </Fieldset>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Button type="submit" variant="primary" icon="upload" busy={busy}>
            Upload
          </Button>
          <Button onClick={reset} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function DocumentsTab({ caseId, canUpload }: { caseId: string; canUpload: boolean }) {
  const docs = useApi<DocumentOut[]>(`/cases/${caseId}/documents`);
  return (
    <div className={s.columns}>
      <Card className={s.main}>
        <Async state={docs} loadingLabel="Loading documents">
          {(list) =>
            list.length === 0 ? (
              <Empty title="No documents yet">Orders arrive automatically; filings and internal papers can be uploaded here.</Empty>
            ) : (
              <div className={s.docGroups}>
                {GROUPS.map((g) => {
                  const items = list.filter((d) => d.doc_group === g.id).sort((a, b) => (b.doc_date ?? b.created_at).localeCompare(a.doc_date ?? a.created_at));
                  if (items.length === 0) return null;
                  return (
                    <section key={g.id} aria-label={g.title}>
                      <div className={s.docGroupHead}>
                        <h3>{g.title}</h3>
                        <span className={s.small}>{g.note}</span>
                      </div>
                      {items.map((d) => (
                        <DocRow key={d.id} d={d} />
                      ))}
                    </section>
                  );
                })}
              </div>
            )
          }
        </Async>
      </Card>
      {canUpload ? <UploadPanel caseId={caseId} onUploaded={docs.reload} /> : null}
    </div>
  );
}
