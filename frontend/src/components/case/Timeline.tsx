"use client";

/**
 * The Timeline tab (design portal-cases, decisions 10 and 13): `/timeline` newest first with the API's label, time
 * and actor, and a short line for the common event types. The payload is never printed as raw JSON.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { TimelineList } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";
import { timelineDetail } from "@/lib/timeline";

import s from "./case.module.css";

export function Timeline({ caseRef }: { caseRef: string }) {
  const [offset, setOffset] = useState(0);
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
            <ol className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.case.timeline}>
              {list.data.items.map((e, i) => {
                const detail = timelineDetail(e.type, e.payload);
                return (
                  <li key={`${e.occurred_at}-${i}`} className={s.note}>
                    <div className={s.noteHead}>
                      <strong>{e.label}</strong>
                      <span className="muted">{formatDateTime(e.occurred_at)}</span>
                      {e.actor_name ? <span>{e.actor_name}</span> : null}
                    </div>
                    {detail ? <div>{detail}</div> : null}
                  </li>
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
