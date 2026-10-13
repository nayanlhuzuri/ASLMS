"use client";

/**
 * Change visibility and Archive on a document row (design portal-workflow, decision 14), shown only where the API's
 * `can_manage` is true and the document is not archived (court records never: the API answers false). 409
 * `already_ingested` explains that a document in the Case Assistant cannot be made private. There is no unarchive and
 * no delete.
 */
import { useState } from "react";

import { Button, CharCounter, ConfirmDialog, RadioGroup, TextArea } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { DocumentItem } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { useWorkflowRefresh, visibilityOptions, within } from "./common";

const REASON_MIN = 3;
const REASON_MAX = 500;

export function DocumentActions({ caseRef, doc }: { caseRef: string; doc: DocumentItem }) {
  const refresh = useWorkflowRefresh(caseRef);
  const action = useAction();
  const [open, setOpen] = useState<"visibility" | "archive" | null>(null);
  const [visibility, setVisibility] = useState("");
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  if (!doc.can_manage || doc.archived_at) return null;
  const path = `/documents/${encodeURIComponent(doc.id)}`;

  function close() {
    setOpen(null);
    setVisibility("");
    setReason("");
    setTried(false);
    action.reset();
  }

  async function changeVisibility() {
    setTried(true);
    if (!visibility || visibility === doc.visibility) return;
    const out = await action.run(() => api(path, { method: "PATCH", body: { visibility } }));
    await refresh();
    if (out.ok) close();
  }

  async function archive() {
    setTried(true);
    if (!within(reason, REASON_MIN, REASON_MAX)) return;
    const out = await action.run(() => api(`${path}/archive`, { method: "POST", body: { reason: reason.trim() } }));
    await refresh();
    if (out.ok) close();
  }

  return (
    <>
      <Button variant="link" onClick={() => setOpen("visibility")}>
        {T.wf.changeVisibility}
      </Button>
      <Button variant="link" onClick={() => setOpen("archive")}>
        {T.wf.archive}
      </Button>
      <ConfirmDialog
        open={open === "visibility"}
        title={T.wf.visibilityTitle}
        onClose={close}
        onConfirm={changeVisibility}
        busy={action.busy}
        error={action.error}
        confirmLabel={T.wf.changeVisibility}
      >
        <RadioGroup
          legend={T.wf.docVisibility}
          name={`doc-visibility-${doc.id}`}
          options={visibilityOptions(doc.visibility)}
          value={visibility}
          onChange={setVisibility}
          error={tried && (!visibility || visibility === doc.visibility) ? T.wf.required : undefined}
        />
      </ConfirmDialog>
      <ConfirmDialog
        open={open === "archive"}
        title={T.wf.archiveTitle}
        onClose={close}
        onConfirm={archive}
        busy={action.busy}
        error={action.error}
        confirmLabel={T.wf.archive}
        danger
      >
        <p className="muted">{T.wf.archiveText}</p>
        <TextArea
          label={T.wf.archiveReason}
          value={reason}
          rows={2}
          maxLength={REASON_MAX}
          aria-required
          hint={T.wf.reasonHint}
          error={tried && !within(reason, REASON_MIN, REASON_MAX) ? T.wf.reasonRequired : undefined}
          onChange={(e) => setReason(e.target.value)}
        />
        <CharCounter value={reason} max={REASON_MAX} />
      </ConfirmDialog>
    </>
  );
}
