"use client";

/**
 * The upload panel and dialog (design portal-workflow, decision 13; Annexure B "Case documents and upload", the panel
 * alongside): file, document type, group only for a type whose group is chosen, document date, description and
 * visibility (nothing pre-selected). The extension and the size are checked against the server's limits before
 * sending; the API still decides by the file's bytes and scans it before anything is stored. The panel says which
 * uploads reach the Case Assistant. Every refusal is put in words; a duplicate links to the document already held.
 */
import { useRef, useState } from "react";

import {
  Button,
  CharCounter,
  Dialog,
  ErrorBanner,
  FileField,
  Notice,
  RadioGroup,
  SelectField,
  TextArea,
  TextField,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useDocumentTypes } from "@/lib/api/hooks";
import type { DocumentItem } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T, UPLOAD_ERRORS } from "@/lib/messages";
import { apiCasePath, refPath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { acceptOf, checkFile, EARLIEST_DOC_DATE, megabytes, todayIst, type FileProblem } from "@/lib/workflow";

import { documentUrl } from "@/components/case/Orders";

import { useWorkflowRefresh, visibilityOptions, within } from "./common";

const DESC_MIN = 3;
const DESC_MAX = 500;

export function problemText(problem: FileProblem): string {
  if (problem.code === "type_not_allowed") return T.wf.preTypeNotAllowed(problem.extensions.join(", "));
  if (problem.code === "too_large") return T.wf.preTooLarge(megabytes(problem.maxBytes));
  return T.wf.preEmpty;
}

export function UploadForm({
  caseRef,
  onUploaded,
  onCancel,
}: {
  caseRef: string;
  onUploaded?: (doc: DocumentItem) => void | Promise<void>;
  onCancel?: () => void;
}) {
  const types = useDocumentTypes();
  const refresh = useWorkflowRefresh(caseRef);
  const action = useAction();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<FileProblem | null>(null);
  const [docType, setDocType] = useState("");
  const [group, setGroup] = useState("");
  const [docDate, setDocDate] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("");
  const [tried, setTried] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const upload = types.data?.upload;
  const items = types.data?.items ?? [];
  const chosen = items.find((t) => t.code === docType);
  const today = todayIst();
  const dateOk = !!docDate && docDate >= EARLIEST_DOC_DATE && docDate <= today;
  const descOk = within(description, DESC_MIN, DESC_MAX);

  function pick(files: File[]) {
    const f = files[0] ?? null;
    setFile(f);
    setNotice(null);
    setProblem(f && upload ? checkFile(f, upload) : null);
  }

  function clear() {
    setFile(null);
    setProblem(null);
    setDocType("");
    setGroup("");
    setDocDate("");
    setDescription("");
    setVisibility("");
    setTried(false);
    if (fileInput.current) fileInput.current.value = "";
  }

  async function submit() {
    setTried(true);
    setNotice(null);
    if (!file || problem || !docType || (chosen?.group_choosable && !group) || !dateOk || !descOk || !visibility) return;
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("doc_type", docType);
    form.append("doc_date", docDate);
    form.append("description", description.trim());
    form.append("visibility", visibility);
    if (chosen?.group_choosable && group) form.append("doc_group", group);
    const out = await action.run(() => api<DocumentItem>(apiCasePath(caseRef, "documents"), { method: "POST", body: form }));
    await refresh();
    if (out.ok) {
      clear();
      setNotice(T.wf.uploaded(out.value.ref_no ?? out.value.original_filename ?? ""));
      await onUploaded?.(out.value);
    }
  }

  const existing =
    action.error instanceof ApiError && action.error.code === "duplicate" && typeof action.error.extra.existing_ref_no === "string"
      ? action.error.extra.existing_ref_no
      : null;
  return (
    <form
      className="stack"
      aria-label={T.wf.upload}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {notice ? <Notice>{notice}</Notice> : null}
      <FileField
        label={T.wf.file}
        accept={acceptOf(upload)}
        inputRef={fileInput}
        aria-required
        hint={upload ? T.wf.fileHint(upload.extensions.join(", "), megabytes(upload.max_bytes)) : undefined}
        error={problem ? problemText(problem) : tried && !file ? T.wf.required : undefined}
        onFiles={pick}
      />
      <SelectField
        label={T.wf.docType}
        options={items.map((t) => ({ value: t.code, label: t.label }))}
        placeholder={T.wf.chooseType}
        value={docType}
        aria-required
        error={tried && !docType ? T.wf.required : undefined}
        onChange={(e) => {
          setDocType(e.target.value);
          setGroup("");
        }}
      />
      {chosen?.group_choosable ? (
        <SelectField
          label={T.wf.docGroup}
          options={[
            { value: "court_filing", label: T.case.docGroups.court_filing! },
            { value: "internal", label: T.case.docGroups.internal! },
          ]}
          placeholder={T.wf.chooseGroup}
          value={group}
          aria-required
          error={tried && !group ? T.wf.required : undefined}
          onChange={(e) => setGroup(e.target.value)}
        />
      ) : null}
      <TextField
        label={T.wf.docDate}
        type="date"
        min={EARLIEST_DOC_DATE}
        max={today}
        value={docDate}
        aria-required
        hint={`${formatDate(EARLIEST_DOC_DATE)} – ${formatDate(today)}`}
        error={tried && !dateOk ? T.wf.dateRange : undefined}
        onChange={(e) => setDocDate(e.target.value)}
      />
      <TextArea
        label={T.wf.docDescription}
        value={description}
        rows={2}
        maxLength={DESC_MAX}
        aria-required
        hint={T.wf.descriptionHint}
        error={tried && !descOk ? T.wf.descriptionHint : undefined}
        onChange={(e) => setDescription(e.target.value)}
      />
      <CharCounter value={description} max={DESC_MAX} />
      <RadioGroup
        legend={T.wf.docVisibility}
        name={`upload-visibility-${refPath(caseRef)}`}
        options={visibilityOptions()}
        value={visibility}
        onChange={setVisibility}
        error={tried && !visibility ? T.wf.required : undefined}
      />
      <p className="muted">{T.wf.assistantLine}</p>
      <ErrorBanner error={action.error} messages={UPLOAD_ERRORS}>
        {existing ? (
          <a href={documentUrl(refPath(existing), "inline")} target="_blank" rel="noopener noreferrer" className="mono">
            {T.wf.openExisting(existing)}
          </a>
        ) : null}
      </ErrorBanner>
      <div className="row">
        {onCancel ? (
          <Button variant="secondary" onClick={onCancel}>
            {T.cancel}
          </Button>
        ) : null}
        <Button type="submit" busy={action.busy}>
          {action.busy ? T.wf.uploading : T.wf.uploadButton}
        </Button>
      </div>
    </form>
  );
}

/** The upload panel of the Documents tab. */
export function UploadPanel({ caseRef }: { caseRef: string }) {
  return (
    <section className="card stack" aria-label={T.wf.upload}>
      <h2>{T.wf.upload}</h2>
      <UploadForm caseRef={caseRef} />
    </section>
  );
}

/** The same form in a dialog (a draft's "Attach a new file"). */
export function UploadDialog({
  open,
  caseRef,
  onClose,
  onUploaded,
  intro,
}: {
  open: boolean;
  caseRef: string;
  onClose: () => void;
  onUploaded: (doc: DocumentItem) => void | Promise<void>;
  intro?: string;
}) {
  return (
    <Dialog open={open} title={T.wf.upload} onClose={onClose}>
      {intro ? <p className="muted">{intro}</p> : null}
      <UploadForm
        caseRef={caseRef}
        onCancel={onClose}
        onUploaded={async (doc) => {
          await onUploaded(doc);
          onClose();
        }}
      />
    </Dialog>
  );
}
