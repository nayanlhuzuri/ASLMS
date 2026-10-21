"use client";

/**
 * The Linked cases tab (design portal-cases, decisions 2 and 11): the list (direction, kind, number, CNR, link source;
 * visible ones linked, others plain text) and the relationship graph (`/links/graph`, depth 2).
 */
import { useQuery } from "@tanstack/react-query";

import { CaseLink, DataTable, EmptyState, ErrorBanner, Loading } from "@/components/ui";
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
          <DataTable
            caption={T.case.links}
            rows={list.data.items.map((l, i) => ({ l, i }))}
            rowKey={(row) => String(row.i)}
            columns={[
              { key: "direction", header: T.case.direction, cell: ({ l }) => l.direction },
              { key: "kind", header: T.case.linkKind, cell: ({ l }) => l.kind },
              {
                key: "case",
                header: T.inbox.case,
                primary: true,
                cell: ({ l }) =>
                  l.case ? (
                    <CaseLink value={l.case} visible={l.visible} />
                  ) : (
                    <span className="mono">{l.case_no_text ?? l.filing_number_text ?? "—"}</span>
                  ),
              },
              { key: "cnr", header: T.case.cnr, cell: ({ l }) => <span className="mono">{l.cnr ?? l.case?.cnr ?? "—"}</span> },
              { key: "source", header: T.case.linkSource, cell: ({ l }) => l.source },
            ]}
          />
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
