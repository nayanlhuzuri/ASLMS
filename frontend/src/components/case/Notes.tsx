"use client";

/**
 * The Notes tab (design portal-cases, decision 10): the trail by `seq_no` with kind, the author's name, designation
 * and office at the time, date, body, visibility badge, "corrects NOTE/…" and "corrected by NOTE/…" links within the
 * page, and attachments with View (only for types a browser shows itself, `canViewInline`, design
 * portal-cases-followups, decision 9) / Download through `/documents/{doc}/file`; "Hide corrected notes" asks the API
 * for `include_superseded=false`.
 *
 * Writing (design portal-workflow, decisions 10-12): the composer when the overview's `workflow.note_mode` is not
 * null, saying before anything is written whether the note will be a draft or permanent; the drafts panel when the
 * caller holds the file or has drafts; Correct on a note only where the API's `can_correct` is true. There is no Edit
 * or Delete on any permanent note. Notes are never sent to SourceTrace.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, Button, CheckField, EmptyState, ErrorBanner, Loading, Notice, Pagination } from "@/components/ui";
import { DraftsPanel } from "@/components/workflow/DraftsPanel";
import { NoteComposer } from "@/components/workflow/NoteComposer";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { Note, NoteList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { canViewInline, pdfDownloadOnly } from "@/lib/documents";
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

function Writing({
  caseRef,
  mode,
  correcting,
  onClearCorrection,
}: {
  caseRef: string;
  mode: "draft" | "permanent";
  correcting: Note | null;
  onClearCorrection: () => void;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <section className="card stack" aria-label={T.wf.writeNote} id="write-note">
      <h2>{T.wf.writeNote}</h2>
      {notice ? <Notice>{notice}</Notice> : null}
      <NoteComposer
        key={correcting?.id ?? "new"}
        caseRef={caseRef}
        secondaryOnly
        mode={mode}
        correcting={correcting}
        onCancel={correcting ? onClearCorrection : undefined}
        onDone={(text) => {
          setNotice(text);
          onClearCorrection();
        }}
      />
    </section>
  );
}

/**
 * A note's attachments with View (only for types a browser shows itself) and Download, each by its function; shared
 * with the remarks history (design case-workspace-admin, decision 15).
 */
export function NoteAttachments({ note }: { note: Note }) {
  const me = useMe();
  const canView = can(me.data, "documents.view");
  const canDownload = can(me.data, "documents.download");
  if (note.attachments.length === 0) return null;
  return (
    <div>
      <span className="muted">{T.case.attachments}:</span>
      <ul>
        {note.attachments.map((a) => (
          <li key={a.id}>
            {a.original_filename ?? a.ref_no ?? a.doc_type} <span className="muted">({sizeText(a.size_bytes)})</span>{" "}
            {canView && canViewInline(a.mime) ? (
              <a href={documentUrl(a.id, "inline")} target="_blank" rel="noopener noreferrer">
                {T.case.view}
              </a>
            ) : null}{" "}
            {canDownload ? (
              <a href={documentUrl(a.id, "attachment")} download>
                {T.case.download}
              </a>
            ) : null}
            {canDownload && pdfDownloadOnly(a.mime) ? <span className="muted"> {T.case.opensAsDownload}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Notes({ caseRef }: { caseRef: string }) {
  // read `/me` with the trail, so the attachments' View and Download links come with the notes
  useMe();
  const detail = useCase(caseRef);
  const [hide, setHide] = useState(false);
  const [offset, setOffset] = useState(0);
  const [correcting, setCorrecting] = useState<Note | null>(null);
  const mode = detail.data?.workflow.note_mode ?? null;
  const showDrafts = mode === "draft" || (detail.data?.counts.my_drafts ?? 0) > 0;
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "notes", hide, offset],
    queryFn: () =>
      api<NoteList>(`${apiCasePath(caseRef)}/notes`, {
        query: { include_superseded: hide ? false : undefined, limit: PAGE, offset },
      }),
  });
  return (
    <div className="stack">
      {showDrafts ? <DraftsPanel caseRef={caseRef} /> : null}
      {mode ? (
        <Writing caseRef={caseRef} mode={mode} correcting={correcting} onClearCorrection={() => setCorrecting(null)} />
      ) : null}
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
                  {n.can_correct && mode ? (
                    <div className="row">
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setCorrecting(n);
                          document.getElementById("write-note")?.scrollIntoView?.({ behavior: "smooth" });
                        }}
                      >
                        {T.wf.correct}
                      </Button>
                    </div>
                  ) : null}
                  <NoteAttachments note={n} />
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
