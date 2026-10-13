"use client";

/**
 * Writing notes (design portal-workflow, decisions 10-12): the composer says before anything is written which kind of
 * note it makes, from the server's `workflow.note_mode` — a draft of the holder (links to the case's documents only)
 * or a permanent note (new files with an internal document type, and links). Kind, body and visibility are required;
 * nothing is pre-selected. A correction fixes the original's kind and visibility. Editing a draft sends only the
 * changed fields, links as document ids. Notes, drafts and attachments are internal: never sent to SourceTrace.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  Button,
  CharCounter,
  CheckField,
  ErrorBanner,
  FileField,
  Notice,
  RadioGroup,
  SelectField,
  TextArea,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useDocumentTypes, useWorkflowCodes } from "@/lib/api/hooks";
import type { DocumentList, Draft, Note } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { apiCasePath, refPath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { acceptOf, checkFile } from "@/lib/workflow";

import { useWorkflowRefresh, visibilityOptions } from "./common";
import { problemText } from "./Upload";

const DEFAULT_ATTACHMENT_TYPE = "correspondence";
const LINKABLE_LIMIT = 200;

export type NoteMode = "draft" | "permanent";

/** The case's documents the caller can open, not archived: the link picker (a link never widens who sees them). */
function useLinkable(caseRef: string) {
  return useQuery({
    queryKey: [...caseKey(caseRef), "documents", "linkable"],
    queryFn: () => api<DocumentList>(apiCasePath(caseRef, "documents"), { query: { limit: LINKABLE_LIMIT } }),
  });
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}

export function NoteComposer({
  caseRef,
  mode,
  correcting,
  draft,
  onDone,
  onCancel,
}: {
  caseRef: string;
  /** From the overview's `workflow.note_mode` (a draft being edited is always `draft`). */
  mode: NoteMode;
  /** The note being corrected: its kind and visibility are kept. */
  correcting?: Note | null;
  /** A draft being edited. */
  draft?: Draft | null;
  onDone?: (notice: string) => void;
  onCancel?: () => void;
}) {
  const codes = useWorkflowCodes();
  const types = useDocumentTypes(mode === "permanent" && !draft);
  const linkable = useLinkable(caseRef);
  const refresh = useWorkflowRefresh(caseRef);
  const action = useAction();
  const fixedKind = correcting?.kind ?? null;
  const fixedVisibility = correcting?.visibility ?? null;
  const [kind, setKind] = useState(draft?.kind ?? fixedKind ?? "");
  const [body, setBody] = useState(draft?.body ?? "");
  const [visibility, setVisibility] = useState(draft?.visibility ?? fixedVisibility ?? "");
  const [links, setLinks] = useState<string[]>(draft?.documents.map((d) => d.id) ?? []);
  const [files, setFiles] = useState<{ file: File; type: string }[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const limits = codes.data?.limits;
  const maxChars = limits?.note_max_chars ?? 20000;
  const maxFiles = limits?.attachments_max_files ?? 5;
  const kinds = (codes.data?.note_kinds ?? []).filter((k) => k.selectable || k.code === fixedKind || k.code === draft?.kind);
  const internalTypes = (types.data?.items ?? []).filter((t) => t.doc_group === "internal");
  const docs = (linkable.data?.items ?? []).filter((d) => !d.archived_at);
  const isCorrection = !!correcting || !!draft?.supersedes;
  const bodyOk = body.trim().length > 0 && body.trim().length <= maxChars;
  const draftMode = mode === "draft" || !!draft;

  function pickFiles(chosen: File[]) {
    setFileError(null);
    const upload = types.data?.upload;
    const next = [...files];
    for (const f of chosen) {
      const problem = upload ? checkFile(f, upload) : null;
      if (problem) {
        setFileError(`${f.name}: ${problemText(problem)}`);
        continue;
      }
      next.push({ file: f, type: DEFAULT_ATTACHMENT_TYPE });
    }
    if (next.length > maxFiles) {
      setFileError(T.wf.tooManyFiles(maxFiles));
      return;
    }
    setFiles(next);
  }

  async function submitNew() {
    const form = new FormData();
    if (!correcting) form.append("kind", kind);
    form.append("body", body.trim());
    form.append("visibility", visibility);
    if (correcting) form.append("supersedes", correcting.ref_no);
    for (const id of links) form.append("document_refs", id);
    if (!draftMode) {
      for (const f of files) {
        form.append("files", f.file, f.file.name);
        form.append("file_doc_types", f.type);
      }
    }
    return api<Note | Draft>(apiCasePath(caseRef, "notes"), { method: "POST", body: form });
  }

  async function submitEdit(d: Draft) {
    const changes: Record<string, unknown> = {};
    if (!isCorrection && kind !== d.kind) changes.kind = kind;
    if (body.trim() !== d.body) changes.body = body.trim();
    if (!isCorrection && visibility !== d.visibility) changes.visibility = visibility;
    const before = d.documents.map((x) => x.id);
    if (!sameSet(before, links)) changes.document_refs = links;
    if (Object.keys(changes).length === 0) return d;
    return api<Draft>(`/notes/drafts/${encodeURIComponent(d.id)}`, { method: "PATCH", body: changes });
  }

  async function submit() {
    setTried(true);
    setNotice(null);
    if (!kind || !bodyOk || !visibility) return;
    const out = await action.run(() => (draft ? submitEdit(draft) : submitNew()));
    await refresh();
    if (!out.ok) return;
    const saved = out.value;
    const text = saved.draft ? T.wf.draftSaved : T.wf.noteAdded((saved as Note).ref_no);
    if (!draft) {
      setBody("");
      setLinks([]);
      setFiles([]);
      setTried(false);
      if (!correcting) {
        setKind("");
        setVisibility("");
      }
    }
    if (onDone) onDone(text);
    else setNotice(text);
  }

  return (
    <form
      className="stack"
      aria-label={draft ? T.wf.editTitle : T.wf.writeNote}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <Notice>{draftMode ? T.wf.composerDraft : T.wf.composerPermanent}</Notice>
      {notice ? <Notice>{notice}</Notice> : null}
      {correcting ? (
        <p>
          <strong>{T.wf.correcting(correcting.ref_no)}</strong> <span className="muted">{T.wf.correctionFixed}</span>
        </p>
      ) : null}
      {draft?.supersedes ? (
        <p>
          <strong>{T.wf.correcting(draft.supersedes.ref_no)}</strong> <span className="muted">{T.wf.correctionFixed}</span>
        </p>
      ) : null}
      <SelectField
        label={T.wf.noteKind}
        options={kinds.map((k) => ({ value: k.code, label: k.label }))}
        placeholder={T.wf.chooseKind}
        value={kind}
        aria-required
        disabled={isCorrection}
        error={tried && !kind ? T.wf.required : undefined}
        onChange={(e) => setKind(e.target.value)}
      />
      <TextArea
        label={T.wf.noteBody}
        value={body}
        rows={5}
        maxLength={maxChars}
        aria-required
        error={tried && !bodyOk ? T.wf.required : undefined}
        onChange={(e) => setBody(e.target.value)}
      />
      <CharCounter value={body} max={maxChars} />
      <RadioGroup
        legend={T.wf.noteVisibility}
        name={`note-visibility-${draft?.id ?? correcting?.id ?? refPath(caseRef)}`}
        options={visibilityOptions()}
        value={visibility}
        disabled={isCorrection}
        onChange={setVisibility}
        error={tried && !visibility ? T.wf.required : undefined}
      />
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend>{T.wf.links}</legend>
        <span className="muted">{T.wf.linksHint}</span>
        {linkable.data && docs.length === 0 ? <span className="muted">{T.wf.noLinkable}</span> : null}
        {docs.map((d) => (
          <CheckField
            key={d.id}
            label={`${d.doc_type_label}${d.ref_no ? ` · ${d.ref_no}` : ""}${d.description ? ` — ${d.description}` : ""}`}
            checked={links.includes(d.id)}
            onChange={(e) => setLinks((prev) => (e.target.checked ? [...prev, d.id] : prev.filter((x) => x !== d.id)))}
          />
        ))}
      </fieldset>
      {!draftMode ? (
        <div className="stack">
          <FileField
            label={T.wf.attachFiles}
            multiple
            accept={acceptOf(types.data?.upload)}
            hint={T.wf.attachHint(maxFiles)}
            error={fileError ?? undefined}
            onFiles={pickFiles}
          />
          {files.map((f, i) => (
            <div key={`${f.file.name}-${i}`} className="row">
              <SelectField
                label={T.wf.attachmentType(f.file.name)}
                options={internalTypes.map((t) => ({ value: t.code, label: t.label }))}
                value={f.type}
                onChange={(e) =>
                  setFiles((prev) => prev.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))
                }
              />
              <Button variant="link" onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}>
                {T.wf.removeFile(f.file.name)}
              </Button>
            </div>
          ))}
        </div>
      ) : null}
      <p className="muted">{T.wf.internalLine}</p>
      <ErrorBanner error={action.error} />
      <div className="row">
        {onCancel ? (
          <Button variant="secondary" onClick={onCancel}>
            {correcting ? T.wf.cancelCorrection : T.cancel}
          </Button>
        ) : null}
        <Button type="submit" busy={action.busy}>
          {draftMode ? T.wf.saveDraft : T.wf.addNote}
        </Button>
      </div>
    </form>
  );
}
