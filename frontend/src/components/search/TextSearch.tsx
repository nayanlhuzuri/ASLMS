"use client";

/**
 * "Order and document text" (design portal-cases, decision 9; plan §5.6 "searched by content"): with
 * `documents.view`, `GET /documents/search` with the API's snippet and the case link; visibility is applied by the API.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, CaseLink, EmptyState, ErrorBanner, Loading, Pagination, Table, TextField } from "@/components/ui";
import { useFilters } from "@/components/inbox/common";
import { api } from "@/lib/api/client";
import type { DocumentSearch } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

export function TextSearch({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const [text, setText] = useState(params.q ?? "");
  const q = (params.q ?? "").trim();
  const offset = offsetOf(params);
  const list = useQuery({
    queryKey: ["documents", "search", q, offset],
    queryFn: () => api<DocumentSearch>("/documents/search", { query: { q, limit: PAGE, offset } }),
    enabled: q.length >= 3,
  });
  return (
    <section className="stack" aria-label={T.search.text}>
      <form
        className="row"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters({ q: text.trim() || undefined });
        }}
      >
        <TextField label={T.search.textBox} value={text} minLength={3} onChange={(e) => setText(e.target.value)} />
        <Button type="submit">{T.search.go}</Button>
      </form>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {q.length >= 3 && list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.search.textNone}</EmptyState>
        ) : (
          <>
            <Table caption={T.search.text}>
              <thead>
                <tr>
                  <th scope="col">{T.search.document}</th>
                  <th scope="col">{T.inbox.case}</th>
                  <th scope="col">{T.search.snippet}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((it) => (
                  <tr key={it.document.id}>
                    <td>
                      <div>{it.document.doc_type_label}</div>
                      <div className="muted">
                        {[it.document.order ? `${it.document.order.kind} ${it.document.order.order_no}` : null, formatDate(it.document.doc_date)]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </td>
                    <td>{it.case ? <CaseLink value={it.case} /> : "—"}</td>
                    <td>{it.snippet ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
    </section>
  );
}
