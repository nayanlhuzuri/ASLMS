"use client";

/**
 * The Timeline tab (design portal-cases, decisions 10 and 13): `/timeline` newest first with the API's label, time
 * and actor, and a short line for the common event types. The payload is never printed as raw JSON. Each row leads
 * with its date in the fixed date column (the alignment rule, design portal-ui-redesign, decision 15).
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DateChip, EmptyState, ErrorBanner, ListRow, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useLabels, useWorkflowCodes } from "@/lib/api/hooks";
import type { TimelineList } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";
import { timelineDetail, type TimelineLabels } from "@/lib/timeline";

import s from "./case.module.css";

function toMap(list: { code: string; label: string }[] | undefined): Record<string, string> {
  return Object.fromEntries((list ?? []).map((x) => [x.code, x.label]));
}

/** The labels the timeline's short lines use (shared with the Overview's Recent activity). */
export function useTimelineLabels(): TimelineLabels {
  const codes = useWorkflowCodes();
  const refLabels = useLabels();
  return {
    reasons: toMap(codes.data?.custody_reasons),
    actions: toMap(codes.data?.pending_actions),
    kinds: toMap(codes.data?.note_kinds),
    stages: toMap(codes.data?.stages),
    alertKinds: toMap(refLabels.data?.alert_kinds),
  };
}

export function Timeline({ caseRef }: { caseRef: string }) {
  const [offset, setOffset] = useState(0);
  const labels = useTimelineLabels();
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "timeline", offset],
    queryFn: () => api<TimelineList>(`${apiCasePath(caseRef)}/timeline`, { query: { limit: PAGE, offset } }),
  });
  return (
    <div className="stack">
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.case.noTimeline}</EmptyState>
        ) : (
          <>
            <ol className={s.plainList} aria-label={T.case.timeline}>
              {list.data.items.map((e, i) => {
                const detail = timelineDetail(e.type, e.payload, labels);
                return (
                  <ListRow key={`${e.occurred_at}-${i}`} as="li" lead={<DateChip date={e.occurred_at} />}>
                    <div className={s.noteHead}>
                      <strong>{e.label}</strong>
                      <span className="muted">{formatDateTime(e.occurred_at)}</span>
                      {e.actor_name ? <span>{e.actor_name}</span> : null}
                    </div>
                    {detail ? <div>{detail}</div> : null}
                  </ListRow>
                );
              })}
            </ol>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </div>
  );
}
