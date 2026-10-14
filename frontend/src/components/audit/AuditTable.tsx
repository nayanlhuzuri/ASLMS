"use client";

/**
 * The audit log list (design portal-audit-health, decision 5): newest first, the time to the second in IST, the
 * action code, who acted (name, designation, office; "System" without a name), the case, the record type and a link
 * to the entry. The name, the office and the action narrow the search shown to that login, office or action. IP
 * address, browser and the before / after values are on the entry page only.
 */
import Link from "next/link";

import { CaseLink, Table } from "@/components/ui";
import type { AuditRow } from "@/lib/api/types";
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

export function AuditTable({ rows, params }: { rows: readonly AuditRow[]; params: Params }) {
  return (
    <Table caption={T.audit.caption}>
      <thead>
        <tr>
          <th scope="col">{T.audit.when}</th>
          <th scope="col">{T.audit.action}</th>
          <th scope="col">{T.audit.by}</th>
          <th scope="col">{T.audit.case}</th>
          <th scope="col">{T.audit.record}</th>
          <th scope="col">
            <span className="visually-hidden">{T.audit.view}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const when = formatDateTimeSeconds(r.at);
          return (
            <tr key={r.id}>
              <td>{when}</td>
              <td>
                <Link href={narrow(params, { action: r.action })} className={s.code}>
                  {r.action}
                </Link>
              </td>
              <td>
                <Actor row={r} params={params} />
              </td>
              <td>{r.case?.ref_no ? <CaseLink value={{ ...r.case, ref_no: r.case.ref_no }} /> : "—"}</td>
              <td className={s.code}>{r.entity_type}</td>
              <td>
                <Link href={`/audit/${r.id}`} aria-label={T.audit.viewEntry(when)} onClick={() => remember(r.id)}>
                  {T.audit.view}
                </Link>
              </td>
            </tr>
          );
        })}
      </tbody>
    </Table>
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
