"use client";

/**
 * Duplicates (design data-load-console, decisions 14-16 and 19): provisional rows waiting for review, rows merged
 * into the row holding their CNR, and the court's own duplicates (linked, never merged); reference, CNR and case
 * number only. "Scan now" needs `admin.data_load`.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button, Chip, ChipGroup, DataTable, EmptyState, ErrorBanner, Loading, Notice, Pagination } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { DedupeScan, DuplicateItem, Duplicates as DuplicatesList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import ds from "./data.module.css";

const LIMIT = 50;
const KINDS = ["review", "merged", "court"] as const;

function brief(c: DuplicateItem["case"]) {
  if (!c) return "—";
  return (
    <>
      <Link href={casePath(c.ref_no)} className="mono">
        {c.ref_no}
      </Link>
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
    <section className={`stack ${ds.panel}`} aria-label={T.data.duplicates}>
      <h2>{T.data.duplicates}</h2>
      <div className="row">
        <ChipGroup label={T.data.duplicates}>
          {KINDS.map((k) => (
            <Chip
              key={k}
              on={k === kind}
              onClick={() => {
                setKind(k);
                setOffset(0);
              }}
            >
              {T.data.dupKinds[k]}
            </Chip>
          ))}
        </ChipGroup>
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
            <DataTable
              caption={T.data.dupKinds[kind]}
              rows={list.data.items}
              rowKey={(d) => `${d.case?.id ?? ""}-${d.other?.id ?? ""}-${d.at}`}
              columns={[
                { key: "case", header: T.data.case, primary: true, cell: (d) => brief(d.case) },
                { key: "other", header: T.data.other, cell: (d) => brief(d.other) },
                { key: "at", header: T.data.at, cell: (d) => formatDateTime(d.at) },
                ...(kind === "review"
                  ? [{ key: "reason", header: T.data.reason, cell: (d: (typeof list.data.items)[number]) => d.reasons ?? "—" }]
                  : []),
              ]}
            />
            <Pagination offset={offset} limit={LIMIT} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}
