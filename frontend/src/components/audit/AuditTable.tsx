"use client";

/**
 * The audit log list (design portal-audit-health, decision 5): newest first, the time to the second in IST, the
 * action code, who acted (name, designation, office; "System" without a name), the case, the record type and a link
 * to the entry. The name, the office and the action narrow the search shown to that login, office or action. IP
 * address, browser and the before / after values are on the entry page only.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";

import { CaseLink, DataTable, type Column } from "@/components/ui";
import type { AuditRow } from "@/lib/api/types";
import { actionName } from "@/lib/audit";
import { formatDateTimeSeconds } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";

import s from "./audit.module.css";

/** The session key naming the entry opened from the search, so its "Back to the search" goes back. */
export const FROM_SEARCH_KEY = "aslms.audit.fromSearch";

function narrow(params: Params, patch: Params): string {
  return "/audit" + queryString({ ...params, ...patch });
}

function remember(id: string) {
  try {
    window.sessionStorage.setItem(FROM_SEARCH_KEY, id);
  } catch {
    // storage unavailable: Back goes to /audit
  }
}

/**
 * The rows on the Work list template (design portal-ui-redesign, decision 26): a `DataTable`, cards on phones, and a
 * row opens its entry page by click or Enter (the before / after values stay on that page, portal-audit-health
 * decision 5). The links inside a row (action, person, office, case) do their own job.
 */
export function AuditTable({ rows, params }: { rows: readonly AuditRow[]; params: Params }) {
  const router = useRouter();
  const columns: Column<AuditRow>[] = [
    { key: "when", header: T.audit.when, width: "190px", cell: (r) => formatDateTimeSeconds(r.at) },
    {
      key: "action",
      header: T.audit.action,
      primary: true,
      cell: (r) => (
        <Link href={narrow(params, { action: r.action })} className={s.code} title={r.action}>
          {actionName(r.action)}
        </Link>
      ),
    },
    { key: "by", header: T.audit.by, cell: (r) => <Actor row={r} params={params} /> },
    {
      key: "case",
      header: T.audit.case,
      cell: (r) => (r.case?.ref_no ? <CaseLink value={{ ...r.case, ref_no: r.case.ref_no }} /> : "—"),
    },
    { key: "record", header: T.audit.record, cell: (r) => <span className={s.code}>{r.entity_type}</span> },
    {
      key: "view",
      header: <span className="visually-hidden">{T.audit.view}</span>,
      hideOnPhone: true,
      align: "right",
      cell: (r) => (
        <Link href={`/audit/${r.id}`} aria-label={T.audit.viewEntry(formatDateTimeSeconds(r.at))} onClick={() => remember(r.id)}>
          {T.audit.view}
        </Link>
      ),
    },
  ];
  return (
    <DataTable
      caption={T.audit.caption}
      columns={columns}
      rows={[...rows]}
      rowKey={(r) => r.id}
      rowLabel={(r) => T.audit.viewEntry(formatDateTimeSeconds(r.at))}
      onRowClick={(r) => {
        remember(r.id);
        router.push(`/audit/${r.id}`);
      }}
    />
  );
}

function Actor({ row, params }: { row: AuditRow; params: Params }) {
  const a = row.actor;
  if (!a.name) return <span>{T.audit.system}</span>;
  return (
    <span className={s.who}>
      {a.user_id ? <Link href={narrow(params, { user: a.user_id })}>{a.name}</Link> : <span>{a.name}</span>}
      {a.designation || a.office_code ? (
        <small>
          {a.designation ?? ""}
          {a.designation && a.office_code ? ", " : ""}
          {a.office_code ? (
            <Link href={narrow(params, { office: a.office_code })} className="mono">
              {a.office_code}
            </Link>
          ) : null}
        </small>
      ) : null}
    </span>
  );
}
