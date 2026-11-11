"use client";

/**
 * What the case-page workflow pieces share (design portal-workflow, decisions 4, 22): the re-read after a write, the
 * three visibility values with one line each, and the working bases that decide the case alerts
 * tab's reader message.
 */
import { useQueryClient } from "@tanstack/react-query";

import { caseKey } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { labelFor } from "@/lib/displayLabels";

export const VISIBILITIES = ["case_scope", "counsel_shared", "private_to_office"] as const;

export function visibilityOptions(current?: string | null) {
  return VISIBILITIES.map((v) => ({
    value: v,
    label: `${labelFor(T.case.visibilities, v)}${current === v ? ` (${T.wf.currentMarkShort})` : ""}`,
    hint: T.wf.visibilityHelp[v],
  }));
}

/** After any write: the case (overview, custody, stages, notes, drafts, documents, timeline, alerts), the caller's
 * alerts and counts, the files lists and the dashboard blocks are read again (decision 22). */
export function useWorkflowRefresh(caseRef: string) {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: caseKey(caseRef) }),
      queryClient.invalidateQueries({ queryKey: ["alerts"] }),
      queryClient.invalidateQueries({ queryKey: ["files"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  };
}

export const WORKING_BASES = ["owner", "allotted", "custody", "counsel"];

/** Text length within bounds (trimmed), as the API counts it. */
export function within(text: string, min: number, max: number): boolean {
  const n = text.trim().length;
  return n >= min && n <= max;
}
