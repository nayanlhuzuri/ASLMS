"use client";

/**
 * Duplicates (design data-load-console, decisions 14-16 and 19): provisional rows waiting for review, rows merged
 * into the row holding their CNR, and the court's own duplicates (linked, never merged); reference, CNR and case
 * number only. "Scan now" needs `admin.data_load`.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, EmptyState, ErrorBanner, Loading, Notice, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DedupeScan, DuplicateItem, Duplicates as DuplicatesList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

const LIMIT = 50;
const KINDS = ["review", "merged", "court"] as const;

function brief(c: DuplicateItem["case"]) {
  if (!c) return "—";
  return (
    <>
      <span className="mono">{c.ref_no}</span>
      <br />
      <span className="mono muted">{[c.cnr, c.case_no_text].filter(Boolean).join(" · ") || "—"}</span>
    </>
  );
}

export function Duplicates() {
  const me = useMe();
  const queryClient = useQueryClient();
  const action = useAction();
  const [kind, setKind] = useState<(typeof KINDS)[number]>("review");
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["data-duplicates", kind, offset],
    queryFn: () => api<DuplicatesList>("/admin/data-load/duplicates", { query: { kind, limit: LIMIT, offset } }),
  });
  async function scan() {
    setMessage(null);
    const out = await action.run(() => api<DedupeScan>("/admin/data-load/duplicates/scan", { method: "POST" }));
    if (out.ok) {
      setMessage(T.data.scanned(out.value.merged, out.value.needs_review, out.value.court_linked));
      await queryClient.invalidateQueries({ queryKey: ["data-duplicates"] });
    }
  }
  return (
    <section className="stack" aria-label={T.data.duplicates}>
      <h2>{T.data.duplicates}</h2>
      <div className="row" role="group" aria-label={T.data.duplicates}>
        {KINDS.map((k) => (
          <Button
            key={k}
            variant={k === kind ? "primary" : "secondary"}
            aria-pressed={k === kind}
            onClick={() => {
              setKind(k);
              setOffset(0);
            }}
          >
            {T.data.dupKinds[k]}
          </Button>
        ))}
        {can(me.data, "admin.data_load") ? (
          <Button variant="secondary" busy={action.busy} onClick={scan}>
            {T.data.scan}
          </Button>
        ) : null}
      </div>
      <ErrorBanner error={action.error ?? list.error} onRetry={() => list.refetch()} />
      {message ? <Notice>{message}</Notice> : null}
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.data.noDuplicates}</EmptyState>
        ) : (
          <>
            <Table caption={T.data.dupKinds[kind]}>
              <thead>
                <tr>
                  <th scope="col">{T.data.case}</th>
                  <th scope="col">{T.data.other}</th>
                  <th scope="col">{T.data.at}</th>
                  {kind === "review" ? <th scope="col">{T.data.reason}</th> : null}
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((d, i) => (
                  <tr key={`${d.case?.id ?? i}-${d.other?.id ?? i}`}>
                    <td>{brief(d.case)}</td>
                    <td>{brief(d.other)}</td>
                    <td>{formatDateTime(d.at)}</td>
                    {kind === "review" ? <td>{d.reasons ?? "—"}</td> : null}
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={LIMIT} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}
