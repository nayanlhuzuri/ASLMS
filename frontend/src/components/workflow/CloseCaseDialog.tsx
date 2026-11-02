"use client";

/**
 * Close This Case (design close-case, decision 19), on the Action dialog template: the body saying what closing does,
 * the drafts line when the caller has drafts on the case, and the required "Why Is This Case Being Closed?" (3 to
 * 2,000 characters, with a counter). It posts `/cases/{ref}/close`; the API decides every refusal, shown in plain
 * words. After closing, a case the caller can still open reloads with the flash naming the note; one they can no longer
 * open (it was with them only to work on) sends them to With Me with the other flash, its cached data marked stale.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CharCounter, ConfirmDialog, Notice, TextArea } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCaseTitle } from "@/lib/api/hooks";
import type { CaseCloseResult } from "@/lib/api/types";
import { setFlash } from "@/lib/flash";
import { CLOSE_ERRORS, T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import { useWorkflowRefresh, within } from "./common";

export const CLOSE_REMARK_MIN = 3;
export const CLOSE_REMARK_MAX = 2000;

export function CloseCaseDialog({
  open,
  caseRef,
  drafts,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  /** The caller's drafts on the case (`counts.my_drafts`). */
  drafts: number;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const refresh = useWorkflowRefresh(caseRef);
  const subtitle = useCaseTitle(caseRef);
  const action = useAction();
  const [remark, setRemark] = useState("");
  const [tried, setTried] = useState(false);
  const ok = within(remark, CLOSE_REMARK_MIN, CLOSE_REMARK_MAX);

  function close() {
    setRemark("");
    setTried(false);
    action.reset();
    onClose();
  }

  async function submit() {
    setTried(true);
    if (!ok) return;
    const out = await action.run(() =>
      api<CaseCloseResult>(apiCasePath(caseRef, "close"), { method: "POST", body: { remark: remark.trim() } }),
    );
    if (!out.ok) {
      await refresh();
      return;
    }
    if (!out.value.visible) {
      setFlash(T.closure.closedAway);
      close();
      router.push("/inbox/with-me");
      void queryClient.cancelQueries({ queryKey: caseKey(caseRef) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: caseKey(caseRef), refetchType: "none" }),
        queryClient.invalidateQueries({ queryKey: ["alerts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
      ]);
      return;
    }
    close();
    onDone(T.closure.closedFlash(out.value.note_ref_no));
    await refresh();
  }

  return (
    <ConfirmDialog
      open={open}
      title={T.closure.closeTitle}
      subtitle={subtitle}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={CLOSE_ERRORS}
      confirmLabel={T.closure.closeCase}
    >
      <p>{T.closure.closeBody}</p>
      {drafts > 0 ? <Notice>{T.closure.closeDrafts}</Notice> : null}
      <TextArea
        label={T.closure.closeField}
        value={remark}
        rows={4}
        maxLength={CLOSE_REMARK_MAX}
        aria-required
        hint={T.closure.remarkHint}
        error={tried && !ok ? T.closure.remarkRequired : undefined}
        onChange={(e) => setRemark(e.target.value)}
      />
      <CharCounter value={remark} max={CLOSE_REMARK_MAX} />
    </ConfirmDialog>
  );
}
