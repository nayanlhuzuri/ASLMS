"use client";

/**
 * The caller's drafts on the case (design portal-workflow, decision 12), above the notes trail when the caller holds
 * the file or has drafts: kind, body, visibility, "corrects NOTE/…", linked documents, written and updated times;
 * Edit (the composer, only the changed fields) and Delete (confirmed; the only delete in a case's records). There is
 * no "make permanent now": drafts become permanent when the file is sent on or recalled. "Attach a new file" uploads
 * a document to the case, then links it to the draft. 409 `draft_finalised` says the draft became a permanent note.
 */
import { useState } from "react";

import { Badge, Button, ConfirmDialog, ErrorBanner, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useCaseTitle, useDrafts, useWorkflowCodes } from "@/lib/api/hooks";
import type { Draft, DocumentItem } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import cs from "@/components/case/case.module.css";

import { useWorkflowRefresh } from "./common";
import { NoteComposer } from "./NoteComposer";
import { UploadDialog } from "./Upload";

function DraftItem({ caseRef, draft, kindLabel }: { caseRef: string; draft: Draft; kindLabel: string }) {
  const refresh = useWorkflowRefresh(caseRef);
  const caseTitle = useCaseTitle(caseRef);
  const remove = useAction();
  const attach = useAction();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function del() {
    const out = await remove.run(() => api(`/notes/drafts/${encodeURIComponent(draft.id)}`, { method: "DELETE" }));
    if (out.ok) setConfirming(false);
    await refresh();
  }

  async function linkNew(doc: DocumentItem) {
    const ids = [...draft.documents.map((d) => d.id), doc.id];
    const out = await attach.run(() =>
      api<Draft>(`/notes/drafts/${encodeURIComponent(draft.id)}`, { method: "PATCH", body: { document_refs: ids } }),
    );
    if (out.ok) setNotice(T.wf.draftSaved);
    await refresh();
  }

  return (
    <li className={cs.note} aria-label={kindLabel}>
      {notice ? <Notice>{notice}</Notice> : null}
      {editing ? (
        <NoteComposer
          caseRef={caseRef}
          secondaryOnly
          mode="draft"
          draft={draft}
          onCancel={() => setEditing(false)}
          onDone={(text) => {
            setEditing(false);
            setNotice(text);
          }}
        />
      ) : (
        <>
          <div className={cs.noteHead}>
            <strong>{kindLabel}</strong>
            <Badge tone="warning">{T.wf.draftBadge}</Badge>
            <Badge>{T.case.visibilities[draft.visibility] ?? draft.visibility}</Badge>
            <span className="muted">{T.wf.created(formatDateTime(draft.created_at))}</span>
            {draft.updated_at !== draft.created_at ? (
              <span className="muted">{T.wf.updated(formatDateTime(draft.updated_at))}</span>
            ) : null}
          </div>
          {draft.supersedes ? <div className="muted">{T.case.corrects(draft.supersedes.ref_no)}</div> : null}
          <p className={cs.noteBody}>{draft.body}</p>
          {draft.documents.length > 0 ? (
            <div>
              <span className="muted">{T.wf.linked}:</span>
              <ul>
                {draft.documents.map((d) => (
                  <li key={d.id}>
                    {d.original_filename ?? d.ref_no ?? d.doc_type}
                    {d.ref_no ? <span className="mono muted"> {d.ref_no}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <ErrorBanner error={attach.error} />
          <div className="row">
            <Button variant="secondary" onClick={() => setEditing(true)}>
              {T.wf.editDraft}
            </Button>
            <Button variant="secondary" onClick={() => setUploading(true)}>
              {T.wf.attachNew}
            </Button>
            <Button variant="danger" onClick={() => setConfirming(true)}>
              {T.wf.deleteDraft}
            </Button>
          </div>
        </>
      )}
      <ConfirmDialog
        subtitle={caseTitle}
        open={confirming}
        title={T.wf.deleteTitle}
        onClose={() => {
          setConfirming(false);
          remove.reset();
        }}
        onConfirm={del}
        busy={remove.busy}
        error={remove.error}
        confirmLabel={T.wf.deleteDraft}
        danger
      >
        <p>{T.wf.deleteText}</p>
      </ConfirmDialog>
      <UploadDialog
        open={uploading}
        caseRef={caseRef}
        intro={T.wf.attachNewLine}
        onClose={() => setUploading(false)}
        onUploaded={linkNew}
      />
    </li>
  );
}

export function DraftsPanel({ caseRef }: { caseRef: string }) {
  const drafts = useDrafts(caseRef);
  const codes = useWorkflowCodes();
  const kindLabel = (code: string) => codes.data?.note_kinds.find((k) => k.code === code)?.label ?? code;
  return (
    <section className="card stack" aria-label={T.wf.drafts}>
      <h2>{T.wf.drafts}</h2>
      <p className="muted">{T.wf.draftsNote}</p>
      {drafts.isPending ? <Loading /> : null}
      <ErrorBanner error={drafts.error} onRetry={() => drafts.refetch()} />
      {drafts.data ? (
        drafts.data.items.length === 0 ? (
          <p className="muted">{T.wf.noDrafts}</p>
        ) : (
          <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
            {drafts.data.items.map((d) => (
              <DraftItem key={d.id} caseRef={caseRef} draft={d} kindLabel={kindLabel(d.kind)} />
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}
