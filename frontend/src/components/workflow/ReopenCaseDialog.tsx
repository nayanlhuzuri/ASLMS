"use client";

/**
 * Reopen This Case (design close-case, decisions 18 and 19), on the Action dialog template: the body saying what
 * reopening does and the required "Why Is This Case Being Reopened?" (3 to 2,000 characters). It posts
 * `/cases/{ref}/reopen`; the case reloads with the flash naming the reopening remark. Refusals show in plain words.
 */
import { useState } from "react";

import { CharCounter, ConfirmDialog, TextArea } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useCaseTitle } from "@/lib/api/hooks";
import type { CaseReopenResult } from "@/lib/api/types";
import { CLOSE_ERRORS, T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import { CLOSE_REMARK_MAX, CLOSE_REMARK_MIN } from "./CloseCaseDialog";
import { useWorkflowRefresh, within } from "./common";

export function ReopenCaseDialog({
  open,
  caseRef,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const refresh = useWorkflowRefresh(caseRef);
  const subtitle = useCaseTitle(caseRef);
  const action = useAction();
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const ok = within(reason, CLOSE_REMARK_MIN, CLOSE_REMARK_MAX);

  function close() {
    setReason("");
    setTried(false);
    action.reset();
    onClose();
  }

  async function submit() {
    setTried(true);
    if (!ok) return;
    const out = await action.run(() =>
      api<CaseReopenResult>(apiCasePath(caseRef, "reopen"), { method: "POST", body: { reason: reason.trim() } }),
    );
    if (out.ok) {
      close();
      onDone(T.closure.reopenedFlash(out.value.note_ref_no));
    }
    await refresh();
  }

  return (
    <ConfirmDialog
      open={open}
      title={T.closure.reopenTitle}
      subtitle={subtitle}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={CLOSE_ERRORS}
      confirmLabel={T.closure.reopenCase}
    >
      <p>{T.closure.reopenBody}</p>
      <TextArea
        label={T.closure.reopenField}
        value={reason}
        rows={4}
        maxLength={CLOSE_REMARK_MAX}
        aria-required
        hint={T.closure.remarkHint}
        error={tried && !ok ? T.closure.remarkRequired : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      <CharCounter value={reason} max={CLOSE_REMARK_MAX} />
    </ConfirmDialog>
  );
}
