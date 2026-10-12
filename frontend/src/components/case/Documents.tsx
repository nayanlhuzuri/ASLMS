"use client";

/**
 * The Documents tab, read-only (design portal-cases, decision 10; Annexure B "Case documents"): grouped Court orders /
 * Court filings / Internal documents (`doc_group`), each with type, date, description, uploader and office, size and
 * pages, "In Case Assistant" / "Not sent to SourceTrace", the visibility badge and the text status; View / Download by
 * function; "Show archived". The upload panel comes with row 13.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, CheckField, EmptyState, ErrorBanner, Loading, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe } from "@/lib/api/hooks";
import type { DocumentItem, DocumentList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";

import { documentUrl } from "./Orders";

const GROUPS = ["court_record", "court_filing", "internal"] as const;

export function sizeText(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${formatNumber(bytes)} B`;
}

function isWord(mime: string): boolean {
  return mime.includes("word") || mime.includes("officedocument");
}

function DocRow({ d, canView, canDownload }: { d: DocumentItem; canView: boolean; canDownload: boolean }) {
  return (
    <tr>
      <td>
        <div>{d.doc_type_label}</div>
        {d.ref_no ? <div className="mono muted">{d.ref_no}</div> : null}
        {d.archived_at ? <Badge>{T.case.archived}</Badge> : null}
      </td>
      <td>{formatDate(d.doc_date)}</td>
      <td>{d.description ?? d.original_filename ?? "—"}</td>
      <td>
        {d.uploaded_by ? (
          <>
            {d.uploaded_by.name}
            {d.uploaded_by.office_code ? <span className="muted"> · {d.uploaded_by.office_code}</span> : null}
          </>
        ) : (
          (d.office?.code ?? "—")
        )}
      </td>
      <td>
        {sizeText(d.size_bytes)}
        {d.page_count ? <div className="muted">{T.case.pages(d.page_count)}</div> : null}
      </td>
      <td>
        <div className="stack">
          {d.assistant_available ? (
            <Badge tone="success">{T.case.inAssistant}</Badge>
          ) : (
            <Badge>{T.case.notSent}</Badge>
          )}
          <Badge>{T.case.visibilities[d.visibility] ?? d.visibility}</Badge>
          <span className="muted">
            {T.case.textStatus}: {d.text_status}
          </span>
        </div>
      </td>
      <td>
        <div className="row">
          {canView && !isWord(d.mime) ? (
            <a href={documentUrl(d.id, "inline")} target="_blank" rel="noopener noreferrer">
              {T.case.view}
            </a>
          ) : null}
          {canDownload ? (
            <a href={documentUrl(d.id, "attachment")} download>
              {T.case.download}
            </a>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

export function Documents({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const [archived, setArchived] = useState(false);
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "documents", archived],
    queryFn: () =>
      api<DocumentList>(`${apiCasePath(caseRef)}/documents`, {
        query: { include_archived: archived || undefined, limit: 200 },
      }),
    enabled: canView,
  });
  if (!canView) return <EmptyState>{T.case.noDocumentAccess}</EmptyState>;
  return (
    <div className="stack">
      <CheckField label={T.case.showArchived} checked={archived} onChange={(e) => setArchived(e.target.checked)} />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data && list.data.items.length === 0 ? <EmptyState>{T.case.noDocuments}</EmptyState> : null}
      {list.data
        ? GROUPS.map((g) => {
            const items = list.data.items.filter((d) => d.doc_group === g);
            if (items.length === 0) return null;
            return (
              <section key={g} aria-label={T.case.docGroups[g]}>
                <h2>{T.case.docGroups[g]}</h2>
                <Table caption={T.case.docGroups[g]}>
                  <thead>
                    <tr>
                      <th scope="col">{T.case.type}</th>
                      <th scope="col">{T.case.orderDate}</th>
                      <th scope="col">{T.case.description}</th>
                      <th scope="col">{T.case.uploadedBy}</th>
                      <th scope="col">{T.case.size}</th>
                      <th scope="col">{T.case.visibility}</th>
                      <th scope="col">
                        <span className="visually-hidden">{T.inbox.actions}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((d) => (
                      <DocRow key={d.id} d={d} canView={canView} canDownload={canDownload} />
                    ))}
                  </tbody>
                </Table>
              </section>
            );
          })
        : null}
    </div>
  );
}
