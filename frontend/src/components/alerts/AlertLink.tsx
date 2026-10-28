"use client";

/**
 * Following an alert (design portal-files-alerts, decision 9): the re-read after a read mark, acknowledge or done, and
 * a link that marks the alert read first, then navigates. "Answer it" (design portal-next-dates, decision 14) takes a
 * `next_date_review` alert whose case the caller can open to the review list narrowed to that case; the list asks the
 * API.
 */
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { AlertItem } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

/** After a read mark, acknowledge or done: the list, the counts and the bell, the dashboard, and the case's tabs. */
export function useAlertRefresh() {
  const queryClient = useQueryClient();
  return async (alert?: AlertItem) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["alerts"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ...(alert?.case ? [queryClient.invalidateQueries({ queryKey: caseKey(alert.case.ref_no) })] : []),
    ]);
  };
}

export async function markRead(ids: string[] | "all") {
  return api<{ marked: number }>("/alerts/read", {
    method: "POST",
    body: ids === "all" ? { all: true } : { alert_ids: ids },
  });
}

/**
 * The subject of an alert as a link that marks the row read first, then navigates (decision 9). A failed mark never
 * blocks the navigation: reading is a convenience, never a gate.
 */
export function AlertLink({
  alert,
  href,
  className,
  children,
}: {
  alert: AlertItem;
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const refresh = useAlertRefresh();
  async function follow(e: MouseEvent<HTMLAnchorElement>) {
    if (alert.read_at || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    try {
      await markRead([alert.id]);
      void refresh(alert);
    } catch {
      // the mark failed: go anyway
    }
    router.push(href);
  }
  return (
    <Link href={href} className={className} onClick={follow}>
      {children}
    </Link>
  );
}

/**
 * Decision 14: "Answer it" on a visible `next_date_review` alert, to `/alerts/next-dates?q=<case id>`; and (design
 * next-date-direct, decision 19) "Correct It" on a `next_date_reported` alert, to the case's Overview with the Correct
 * dialog open (shown there only while the server's `workflow.next_date_correct` allows it).
 */
export function AnswerIt({ alert }: { alert: AlertItem }) {
  if (!alert.case || !alert.case_visible) return null;
  if (alert.kind === "next_date_reported") {
    return (
      <AlertLink alert={alert} href={`${casePath(alert.case.ref_no)}?nd=correct`}>
        {T.nd.correct}
      </AlertLink>
    );
  }
  if (alert.kind !== "next_date_review") return null;
  return (
    <AlertLink alert={alert} href={`/alerts/next-dates?q=${encodeURIComponent(alert.case.id)}`}>
      {T.nd.answerIt}
    </AlertLink>
  );
}
