"use client";

/**
 * The before / after values of one audit entry (design portal-audit-health, decision 6): one row per key of the
 * union of both, in the order the keys appear, with a "Changed" mark where they differ. Objects and lists show as
 * indented JSON; a withheld text (`{length, sha256}`) says the text was not kept, with its length and fingerprint;
 * `null` or absent shows "—".
 */
import { DataTable, EmptyState } from "@/components/ui";
import { diffRows, isTextDigest, VALUE_KEY } from "@/lib/audit";
import { T } from "@/lib/messages";

import s from "./audit.module.css";

export function AuditValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>—</span>;
  if (isTextDigest(value)) {
    return <span>{T.audit.digest(String(value.length), String(value.sha256).slice(0, 12))}</span>;
  }
  if (typeof value === "object") return <pre className={s.json}>{JSON.stringify(value, null, 2)}</pre>;
  if (typeof value === "string") return <span className={s.code}>{value === "" ? " " : value}</span>;
  return <span className={s.code}>{String(value)}</span>;
}

export function BeforeAfter({ before, after }: { before: unknown; after: unknown }) {
  const rows = diffRows(before, after);
  if (rows.length === 0) return <EmptyState>{T.audit.noValues}</EmptyState>;
  return (
    <DataTable
      caption={T.audit.beforeAfter}
      rows={rows}
      rowKey={(r) => r.key}
      rowClassName={(r) => (r.changed ? s.changedRow : undefined)}
      columns={[
        {
          key: "field",
          header: T.audit.field,
          primary: true,
          rowHeader: true,
          cell: (r) => <span className={s.code}>{r.key === VALUE_KEY ? T.audit.value : r.key}</span>,
        },
        { key: "before", header: T.audit.before, cell: (r) => <AuditValue value={r.before} /> },
        { key: "after", header: T.audit.after, cell: (r) => <AuditValue value={r.after} /> },
        {
          key: "changed",
          header: T.audit.changed,
          cell: (r) => (r.changed ? <span className={s.mark}>{T.audit.changed}</span> : null),
        },
      ]}
    />
  );
}
