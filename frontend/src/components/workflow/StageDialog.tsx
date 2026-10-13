"use client";

/**
 * Set stage (design portal-workflow, decision 9), shown when the overview's `workflow.set_stage` is true: the stages
 * of `/workflow/codes` grouped by phase in `sort_order` with the current one marked, the response mode pre-filled
 * with the current one (the API carries it forward), an optional note. 409 `unchanged` shows the server's message.
 */
import { useState } from "react";

import { CharCounter, ConfirmDialog, SelectField, TextArea } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useWorkflowCodes } from "@/lib/api/hooks";
import type { StageCode } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import { useWorkflowRefresh } from "./common";

const NOTE_MAX = 2000;

function byPhase(stages: StageCode[]): [string, StageCode[]][] {
  const groups = new Map<string, StageCode[]>();
  for (const s of [...stages].sort((a, b) => a.sort_order - b.sort_order)) {
    const list = groups.get(s.phase) ?? [];
    list.push(s);
    groups.set(s.phase, list);
  }
  return [...groups.entries()];
}

export function StageDialog({
  open,
  caseRef,
  current,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  current: { stage: string; response_mode: string } | null;
  onClose: () => void;
  onDone?: (notice: string) => void;
}) {
  const codes = useWorkflowCodes(open);
  const refresh = useWorkflowRefresh(caseRef);
  const action = useAction();
  const [stage, setStage] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  // pre-filled with the current mode; a first stage takes the API's default, "by the department"
  const responseMode = mode ?? current?.response_mode ?? "department";

  function close() {
    setStage("");
    setMode(null);
    setNote("");
    setTried(false);
    action.reset();
    onClose();
  }

  async function submit() {
    setTried(true);
    if (!stage) return;
    const out = await action.run(() =>
      api(apiCasePath(caseRef, "stages"), {
        method: "POST",
        body: { stage, response_mode: responseMode || null, note: note.trim() || null },
      }),
    );
    if (out.ok) {
      close();
      onDone?.(T.wf.stageSaved);
    }
    await refresh();
  }

  return (
    <ConfirmDialog
      open={open}
      title={T.wf.stageTitle}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      confirmLabel={T.wf.setStage}
    >
      <SelectField
        label={T.wf.stageBlock}
        options={[]}
        groups={byPhase(codes.data?.stages ?? []).map(([phase, list]) => ({
          label: phase,
          options: list.map((s) => ({ value: s.code, label: `${s.label}${current?.stage === s.code ? T.wf.currentMark : ""}` })),
        }))}
        placeholder={T.wf.chooseStage}
        value={stage}
        aria-required
        error={tried && !stage ? T.wf.required : undefined}
        onChange={(e) => setStage(e.target.value)}
      />
      <SelectField
        label={T.wf.responseMode}
        options={(codes.data?.response_modes ?? []).map((m) => ({ value: m.code, label: m.label }))}
        value={responseMode}
        onChange={(e) => setMode(e.target.value)}
      />
      <TextArea label={T.wf.stageNote} value={note} rows={2} maxLength={NOTE_MAX} onChange={(e) => setNote(e.target.value)} />
      <CharCounter value={note} max={NOTE_MAX} />
    </ConfirmDialog>
  );
}
