"use client";

/**
 * The Linked cases tab (design portal-cases, decisions 2 and 11): the list (direction, kind, number, CNR, link source;
 * visible ones linked, others plain text) and the relationship graph (`/links/graph`, depth 2).
 */
import { useQuery } from "@tanstack/react-query";

import { CaseLink, EmptyState, ErrorBanner, Loading, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase } from "@/lib/api/hooks";
import type { LinkGraph as LinkGraphOut, LinkList } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";

import { LinkGraph } from "./LinkGraph";

export function Links({ caseRef }: { caseRef: string }) {
  const overview = useCase(caseRef);
  const base = apiCasePath(caseRef);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "links"],
    queryFn: () => api<LinkList>(`${base}/links`),
  });
  const graph = useQuery({
    queryKey: [...caseKey(caseRef), "links", "graph"],
    queryFn: () => api<LinkGraphOut>(`${base}/links/graph`, { query: { depth: 2 } }),
    enabled: (list.data?.items.length ?? 0) > 0,
  });
  return (
    <div className="stack">
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.case.noLinks}</EmptyState>
        ) : (
          <Table caption={T.case.links}>
            <thead>
              <tr>
                <th scope="col">{T.case.direction}</th>
                <th scope="col">{T.case.linkKind}</th>
                <th scope="col">{T.inbox.case}</th>
                <th scope="col">{T.case.cnr}</th>
                <th scope="col">{T.case.linkSource}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((l, i) => (
                <tr key={i}>
                  <td>{l.direction}</td>
                  <td>{l.kind}</td>
                  <td>
                    {l.case ? (
                      <CaseLink value={l.case} visible={l.visible} />
                    ) : (
                      <span className="mono">{l.case_no_text ?? l.filing_number_text ?? "—"}</span>
                    )}
                  </td>
                  <td className="mono">{l.cnr ?? l.case?.cnr ?? "—"}</td>
                  <td>{l.source}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )
      ) : null}
      {graph.data && graph.data.nodes.length > 0 ? (
        <section aria-label={T.case.graph}>
          <h2>{T.case.graph}</h2>
          <LinkGraph graph={graph.data} rootId={overview.data?.id ?? null} />
        </section>
      ) : null}
      <ErrorBanner error={graph.error} />
    </div>
  );
}
