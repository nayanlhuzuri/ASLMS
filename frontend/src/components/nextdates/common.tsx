"use client";

/**
 * What the next-date pieces share (design portal-next-dates, decisions 9, 16 and 17): the re-read after an action, the
 * stale-answer test, the case's name in labels and the checks made on a date and a note before they are sent (the
 * API checks again and decides).
 */
import { useQueryClient } from "@tanstack/react-query";

import { useWorkflowRefresh } from "@/components/workflow/common";
import { ApiError } from "@/lib/api/client";
import type { NextDateReviewItem } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { todayIst } from "@/lib/workflow";

/** The note on a next date: a short public remark (`NextDateRejectIn` / `NextDateEnterIn`). */
export const NOTE_MAX = 300;

export const NEXT_DATES_KEY = ["next-dates"] as const;

/**
 * After confirm, reject or enter (decision 16): the case (with its next dates and its queue items), the caller's
 * alerts with the calendar and counts, the files lists, the dashboard blocks and the review list are read again.
 */
export function useNextDateRefresh(caseRef: string) {
  const queryClient = useQueryClient();
  const workflow = useWorkflowRefresh(caseRef);
  return async () => {
    await Promise.all([workflow(), queryClient.invalidateQueries({ queryKey: NEXT_DATES_KEY })]);
  };
}

/** A 409 `not_pending`: the item was answered or replaced meanwhile, so the list and the case are read again. */
export function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.code === "not_pending";
}

/** The case as people know it: its number, else its reference. */
export function caseName(c: Pick<NextDateReviewItem["case"], "case_no_text" | "ref_no">): string {
  return c.case_no_text || c.ref_no;
}

/** Decision 9: the date field's own check (required where asked, never before today in IST). */
export function dateProblem(value: string, { required }: { required: boolean }): string | null {
  if (!value) return required ? T.nd.dateRequired : null;
  if (value < todayIst()) return T.nd.dateTooEarly;
  return null;
}

export function noteProblem(value: string): string | null {
  return value.trim().length > NOTE_MAX ? T.nd.noteTooLong(NOTE_MAX) : null;
}
