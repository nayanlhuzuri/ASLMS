"use client";

/**
 * "Order and document text" (design portal-cases, decision 9; plan §5.6 "searched by content"): with
 * `documents.view`, `GET /documents/search` with the API's snippet and the case link; visibility is applied by the API.
 * The one filter bar (design portal-filters): the words, the document group and type and the document date range (the
 * API's `group`, `doc_type`, `date_from`, `date_to`). Under the box, the note that scanned documents, images and old
 * Word files are not searched by their content (design document-ocr, decision 3; no OCR in Phase 1). The results are a
 * `DataTable`, cards on phones (design portal-ui-redesign, decision 26).
 */
import { useQuery } from "@tanstack/react-query";
import { FilterBar } from "@/components/filters/FilterBar";
import { CaseLink, DataTable, EmptyState, ErrorBanner, Loading, Pagination, type Column } from "@/components/ui";
import { useFilters } from "@/components/inbox/common";
import { api } from "@/lib/api/client";
import { useDocumentTypes } from "@/lib/api/hooks";
import type { DocumentSearch } from "@/lib/api/types";

type Hit = DocumentSearch["items"][number];
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";

export function TextSearch({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const types = useDocumentTypes();
  const q = (params.q ?? "").trim();
  const offset = offsetOf(params);
  const group = params.group || undefined;
  const query = {
    q,
    group,
    doc_type: params.doc_type || undefined,
    date_from: params.date_from || undefined,
    date_to: params.date_to || undefined,
    limit: PAGE,
    offset,
  };
  const list = useQuery({
    queryKey: ["documents", "search", query],
    queryFn: () => api<DocumentSearch>("/documents/search", { query }),
    enabled: q.length >= 3,
  });
  const columns: Column<Hit>[] = [
    {
      key: "document",
      header: T.search.document,
      primary: true,
      cell: (it) => (
        <>
          <div>{it.document.doc_type_label}</div>
          <div className="muted">
            {[it.document.order ? `${it.document.order.kind} ${it.document.order.order_no}` : null, formatDate(it.document.doc_date)]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </>
      ),
    },
    { key: "case", header: T.inbox.case, cell: (it) => (it.case ? <CaseLink value={it.case} /> : "—") },
    { key: "snippet", header: T.search.snippet, cell: (it) => it.snippet ?? "—" },
  ];
  const typeOptions = (types.data?.items ?? [])
    .filter((t) => !group || t.doc_group === group)
    .map((t) => ({ value: t.code, label: t.label }));
  return (
    <section className="stack" aria-label={T.search.text}>
      <FilterBar
        list="documents"
        params={params}
        wordsLabel={T.search.textBox}
        own={[
          {
            key: "group",
            kind: "select",
            label: T.search.docGroup,
            placeholder: T.search.anyGroup,
            options: Object.entries(T.case.docGroups).map(([value, label]) => ({ value, label })),
          },
          { key: "doc_type", kind: "select", label: T.search.docType, placeholder: T.search.anyDocType, options: typeOptions },
          { key: "date_from", kind: "date", label: T.search.docDateFrom },
          { key: "date_to", kind: "date", label: T.search.docDateTo },
        ]}
        ownRanges={[["date_from", "date_to"]]}
        total={q.length >= 3 ? list.data?.total : undefined}
        noun="documents"
      />
      <p className="muted">{T.search.textNotSearched}</p>
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {q.length >= 3 && list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.search.textNone}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.search.text}
              columns={columns}
              rows={list.data.items}
              rowKey={(it) => it.document.id}
            />
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
    </section>
  );
}
