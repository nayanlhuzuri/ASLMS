"use client";

/**
 * The Notes tab, read-only (design portal-cases, decision 10): the trail by `seq_no` with kind, the author's name,
 * designation and office at the time, date, body, visibility badge, "corrects NOTE/…" and "corrected by NOTE/…" links
 * within the page, and attachments with View / Download through `/documents/{doc}/file`; "Hide corrected notes" asks
 * the API for `include_superseded=false`. Writing notes and drafts come with row 13. Notes are never sent to
 * SourceTrace.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, CheckField, EmptyState, ErrorBanner, Loading, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe } from "@/lib/api/hooks";
import type { NoteList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { PAGE } from "@/lib/params";

import s from "./case.module.css";
import { sizeText } from "./Documents";
import { documentUrl } from "./Orders";

function anchor(seq: number): string {
  return `note-${seq}`;
}

export function Notes({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const [hide, setHide] = useState(false);
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "notes", hide, offset],
    queryFn: () =>
      api<NoteList>(`${apiCasePath(caseRef)}/notes`, {
        query: { include_superseded: hide ? false : undefined, limit: PAGE, offset },
      }),
  });
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  return (
    <div className="stack">
      <CheckField
        label={T.case.hideCorrected}
        checked={hide}
        onChange={(e) => {
          setHide(e.target.checked);
          setOffset(0);
        }}
      />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.case.noNotes}</EmptyState>
        ) : (
          <>
            <ol className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.case.notes}>
              {list.data.items.map((n) => (
                <li key={n.id} id={anchor(n.seq_no)} className={s.note}>
                  <div className={s.noteHead}>
                    <strong>{n.kind_label}</strong>
                    <span className="mono muted">{n.ref_no}</span>
                    <span>
                      {[n.author.name, n.author.designation, n.author.office_code].filter(Boolean).join(", ")}
                    </span>
                    <span className="muted">{formatDateTime(n.created_at)}</span>
                    <Badge>{T.case.visibilities[n.visibility] ?? n.visibility}</Badge>
                  </div>
                  {n.supersedes ? (
                    <div className="muted">
                      <a href={`#${anchor(n.supersedes.seq_no)}`}>{T.case.corrects(n.supersedes.ref_no)}</a>
                    </div>
                  ) : null}
                  {n.superseded_by ? (
                    <div>
                      <Badge tone="warning">
                        <a href={`#${anchor(n.superseded_by.seq_no)}`}>{T.case.correctedBy(n.superseded_by.ref_no)}</a>
                      </Badge>
                    </div>
                  ) : null}
                  <p className={s.noteBody}>{n.body}</p>
                  {n.attachments.length > 0 ? (
                    <div>
                      <span className="muted">{T.case.attachments}:</span>
                      <ul>
                        {n.attachments.map((a) => (
                          <li key={a.id}>
                            {a.original_filename ?? a.ref_no ?? a.doc_type} <span className="muted">({sizeText(a.size_bytes)})</span>{" "}
                            {canView ? (
                              <a href={documentUrl(a.id, "inline")} target="_blank" rel="noopener noreferrer">
                                {T.case.view}
                              </a>
                            ) : null}{" "}
                            {canDownload ? (
                              <a href={documentUrl(a.id, "attachment")} download>
                                {T.case.download}
                              </a>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </div>
  );
}
