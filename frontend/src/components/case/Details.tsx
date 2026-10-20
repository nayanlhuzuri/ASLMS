"use client";

/**
 * The Details tab (design portal-cases, decision 10): every other typed field of the overview response, so each NAPIX
 * field with a home is visible somewhere (CLAUDE.md "every NAPIX field is kept"): identity, status, classification,
 * place, acts and sections, lower courts, applications, objections, court transfers, writ information, the parties
 * and advocates as printed, and the portal block. Internal ids are not shown.
 */
import type { ReactNode } from "react";

import { DefinitionList, Table } from "@/components/ui";
import { useCase } from "@/lib/api/hooks";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** `date_first_list` → "Date first list". */
export function fieldLabel(key: string): string {
  const text = key.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function fieldValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? T.yes : T.no;
  if (typeof value === "number") return String(value);
  if (typeof value === "string") {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
    if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
    return value;
  }
  if (Array.isArray(value)) return value.map((v) => String(fieldValue(v))).join(", ") || "—";
  return "—";
}

function shown(key: string, value: unknown): boolean {
  return !(typeof value === "string" && UUID.test(value)) && key !== "id";
}

function Block({ title, data }: { title: string; data: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(data ?? {}).filter(([k, v]) => shown(k, v));
  return (
    <section className="card stack" aria-label={title}>
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="muted">{T.case.none}</p>
      ) : (
        <DefinitionList items={entries.map(([k, v]) => [fieldLabel(k), fieldValue(v)])} />
      )}
    </section>
  );
}

function ListBlock({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => rows.some((r) => shown(k, r[k])));
  return (
    <section className="card stack" aria-label={title}>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="muted">{T.case.none}</p>
      ) : (
        <Table caption={title}>
          <thead>
            <tr>
              {keys.map((k) => (
                <th key={k} scope="col">
                  {fieldLabel(k)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {keys.map((k) => (
                  <td key={k}>{shown(k, r[k]) ? fieldValue(r[k]) : "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </section>
  );
}

export function Details({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const c = query.data;
  const bench = c.bench ? { bench_id: c.bench.bench_id, bench_name: c.bench.bench_name, judge_names: c.bench.judge_names } : null;
  return (
    <div className="stack">
      <Block title={T.case.identity} data={{ ...c.identity, court: c.court?.name ?? null, est_code: c.court?.est_code ?? null }} />
      <Block title={T.case.statusBlock} data={c.status} />
      <Block title={T.case.classification} data={{ ...c.classification, ...(bench ? { sitting_bench: bench.bench_name, judges: bench.judge_names } : {}) }} />
      <Block title={T.case.place} data={c.place} />
      <Block title={T.case.asPrinted} data={c.parties_as_printed} />
      <ListBlock title={T.case.acts} rows={c.acts} />
      <ListBlock title={T.case.lowerCourts} rows={c.lower_courts} />
      <ListBlock title={T.case.applications} rows={c.applications} />
      <ListBlock title={T.case.objections} rows={c.objections} />
      <ListBlock title={T.case.courtTransfers} rows={c.court_transfers} />
      <ListBlock title={T.case.writInfo} rows={c.writ_info} />
      <Block title={T.case.portal} data={c.portal} />
    </div>
  );
}

/** The identity and classification fields only (design portal-ui-redesign, decision 7: the claim modal's "Case
 * details" tab). */
export function IdentityDetails({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const c = query.data;
  return (
    <div className="stack">
      <Block title={T.case.identity} data={{ ...c.identity, court: c.court?.name ?? null, est_code: c.court?.est_code ?? null }} />
      <Block title={T.case.classification} data={c.classification} />
    </div>
  );
}
