"use client";

/**
 * The lists of the chosen bench (design portal-causelist, decision 9): each with its type, its stored entries and the
 * court's original PDF — View (inline, `documents.view`) opens the relay's file in a new tab under the API's headers,
 * Download (`documents.download`) saves it; a list without a stored PDF says so. A corrected list (a later version of
 * the list the court re-issued under the same number; design court-data-freshness, decision 17) carries a "Corrected
 * list" badge with the time it was received and an "Earlier version" link that opens the version it replaced.
 */
import { Badge, Button } from "@/components/ui";
import type { CauselistBench } from "@/lib/api/types";
import { canViewInline } from "@/lib/documents";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./causelist.module.css";

export function listFileUrl(listId: string, disposition: "inline" | "attachment"): string {
  return `/api/backend/causelists/lists/${encodeURIComponent(listId)}/file?disposition=${disposition}`;
}

export function ListStrip({
  bench,
  canView,
  canDownload,
  onEarlier,
}: {
  bench: CauselistBench;
  canView: boolean;
  canDownload: boolean;
  onEarlier?: (listId: string) => void;
}) {
  if (bench.lists.length === 0) return <p className="muted">{T.causelist.noListPublished}</p>;
  return (
    <section aria-label={T.causelist.lists} className="stack">
      <h2>{T.causelist.lists}</h2>
      <ul className={s.lists}>
        {bench.lists.map((l) => (
          <li key={l.id}>
            <strong>{T.causelist.listTypes[l.list_type] ?? l.list_type_text ?? l.list_type}</strong>
            {l.list_type_text && l.list_type === "other" ? <span className="muted">{l.list_type_text}</span> : null}
            <span className="muted">{T.causelist.listEntries(l.entries_stored)}</span>
            {(l.version ?? 1) > 1 ? (
              <span className="row">
                <Badge tone="info">{T.causelist.corrected}</Badge>
                {l.corrected_at ? <span className="muted">{T.causelist.correctedAt(formatDateTime(l.corrected_at))}</span> : null}
                {l.supersedes_id && onEarlier ? (
                  <Button variant="link" onClick={() => onEarlier(l.supersedes_id!)}>
                    {T.causelist.earlierVersion}
                  </Button>
                ) : null}
              </span>
            ) : null}
            {l.has_pdf ? (
              <span className="row">
                {canView && canViewInline("application/pdf") ? (
                  <a href={listFileUrl(l.id, "inline")} target="_blank" rel="noopener noreferrer">
                    {T.causelist.view}
                  </a>
                ) : null}
                {canDownload ? (
                  <a href={listFileUrl(l.id, "attachment")} download>
                    {T.causelist.download}
                  </a>
                ) : null}
              </span>
            ) : (
              <span className="muted">{l.fetch_status === "pending" ? T.causelist.pdfPending : T.causelist.noPdf}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
