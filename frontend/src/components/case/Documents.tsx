"use client";

/**
 * The Documents tab (design portal-cases, decision 10; Annexure B "Case documents and upload"): grouped Court orders /
 * Court filings / Internal documents (`doc_group`), each with type, date, description, uploader and office, size and
 * pages, "In Case Assistant" / "Not sent to SourceTrace", the visibility badge and the text status in plain words
 * (`textLabel`, design document-ocr: "Scanned, not read" and the others); View / Download by
 * function; "Show archived". The upload panel sits alongside when the overview's `workflow.upload` is true, and each
 * row the API marks `can_manage` offers Change visibility and Archive (design portal-workflow, decisions 13, 14).
 *
 * Each group is its own query of 50 with its own pager and the API's `total` (design portal-cases-followups,
 * decision 8); an empty group is not shown, "No documents" when all three are empty; "Show archived" applies to all
 * three. View only for types a browser shows itself (`canViewInline`, decisions 9 and 10).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, CheckField, EmptyState, ErrorBanner, Loading, Pagination, Table } from "@/components/ui";
import { DocumentActions } from "@/components/workflow/DocumentActions";
import { UploadPanel } from "@/components/workflow/Upload";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { DocumentItem, DocumentList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { canViewInline, pdfDownloadOnly, textLabel } from "@/lib/documents";
import { formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { PAGE } from "@/lib/params";
import { apiCasePath } from "@/lib/refs";

import { documentUrl } from "./Orders";

const GROUPS = ["court_record", "court_filing", "internal"] as const;

export function sizeText(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${formatNumber(bytes)} B`;
}

function DocRow({
  caseRef,
  d,
  canView,
  canDownload,
}: {
  caseRef: string;
  d: DocumentItem;
  canView: boolean;
  canDownload: boolean;
}) {
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
            {T.case.textStatus}: {textLabel(d)}
          </span>
        </div>
      </td>
      <td>
        <div className="row">
          {canView && canViewInline(d.mime) ? (
            <a href={documentUrl(d.id, "inline")} target="_blank" rel="noopener noreferrer">
              {T.case.view}
            </a>
          ) : null}
          {canDownload ? (
            <a href={documentUrl(d.id, "attachment")} download>
              {T.case.download}
            </a>
          ) : null}
          {canDownload && pdfDownloadOnly(d.mime) ? <span className="muted">{T.case.opensAsDownload}</span> : null}
          <DocumentActions caseRef={caseRef} doc={d} />
        </div>
      </td>
    </tr>
  );
}

type Group = (typeof GROUPS)[number];

function useGroup(caseRef: string, group: Group, archived: boolean, offset: number, enabled: boolean) {
  return useQuery({
    queryKey: [...caseKey(caseRef), "documents", group, archived, offset],
    queryFn: () =>
      api<DocumentList>(`${apiCasePath(caseRef)}/documents`, {
        query: { group, include_archived: archived || undefined, limit: PAGE, offset },
      }),
    enabled,
    placeholderData: keepPreviousData, // the group stays on screen while its next page loads
  });
}

function GroupSection({
  caseRef,
  group,
  list,
  offset,
  onPage,
  canView,
  canDownload,
}: {
  caseRef: string;
  group: Group;
  list: DocumentList;
  offset: number;
  onPage: (offset: number) => void;
  canView: boolean;
  canDownload: boolean;
}) {
  const title = T.case.docGroups[group]!;
  return (
    <section aria-label={title}>
      <h2>{title}</h2>
      <p className="muted">{T.case.groupTotal(formatNumber(list.total))}</p>
      <Table caption={title}>
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
          {list.items.map((d) => (
            <DocRow key={d.id} caseRef={caseRef} d={d} canView={canView} canDownload={canDownload} />
          ))}
        </tbody>
      </Table>
      <Pagination offset={offset} limit={PAGE} total={list.total} onChange={onPage} />
    </section>
  );
}

const START: Record<Group, number> = { court_record: 0, court_filing: 0, internal: 0 };

export function Documents({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const detail = useCase(caseRef);
  const canUpload = detail.data?.workflow.upload ?? false;
  const [archived, setArchived] = useState(false);
  const [offsets, setOffsets] = useState<Record<Group, number>>(START);
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  const records = useGroup(caseRef, "court_record", archived, offsets.court_record, canView);
  const filings = useGroup(caseRef, "court_filing", archived, offsets.court_filing, canView);
  const internal = useGroup(caseRef, "internal", archived, offsets.internal, canView);
  const queries: Record<Group, typeof records> = { court_record: records, court_filing: filings, internal };
  if (!canView) return canUpload ? <UploadPanel caseRef={caseRef} /> : <EmptyState>{T.case.noDocumentAccess}</EmptyState>;
  const all = GROUPS.map((g) => queries[g]);
  const pending = all.some((q) => q.isPending);
  const error = all.find((q) => q.error)?.error ?? null;
  const empty = !pending && all.every((q) => q.data && q.data.total === 0);
  return (
    <div className="stack">
      {canUpload ? <UploadPanel caseRef={caseRef} /> : null}
      <CheckField
        label={T.case.showArchived}
        checked={archived}
        onChange={(e) => {
          setArchived(e.target.checked);
          setOffsets(START);
        }}
      />
      {pending ? <Loading /> : null}
      <ErrorBanner error={error} onRetry={() => all.forEach((q) => q.error && q.refetch())} />
      {empty ? <EmptyState>{T.case.noDocuments}</EmptyState> : null}
      {GROUPS.map((g) => {
        const data = queries[g].data;
        if (!data || data.total === 0) return null;
        return (
          <GroupSection
            key={g}
            caseRef={caseRef}
            group={g}
            list={data}
            offset={offsets[g]}
            onPage={(o) => setOffsets((prev) => ({ ...prev, [g]: o }))}
            canView={canView}
            canDownload={canDownload}
          />
        );
      })}
    </div>
  );
}
