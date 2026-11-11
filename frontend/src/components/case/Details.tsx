"use client";

/**
 * The Details tab (design portal-cases, decision 10): every other typed field of the overview response, so each NAPIX
 * field with a home is visible somewhere (CLAUDE.md "every NAPIX field is kept"): identity, status, classification,
 * place, acts and sections, lower courts, applications, objections, court transfers, writ information, the parties
 * and advocates as printed, and the portal block. Each key has a plain label from `lib/caseFields.ts` and coded values
 * are named (design portal-names-and-labels, decisions 17-19); internal ids are hidden by name. Every list shares one
 * label column width.
 */
import type { ReactNode } from "react";

import { DataTable, DefinitionList, EmptyState } from "@/components/ui";
import { useCase } from "@/lib/api/hooks";
import { caseFieldLabel, caseFieldValue, HIDDEN_FIELDS, type FieldBlock } from "@/lib/caseFields";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./case.module.css";

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

function shown(key: string): boolean {
  return !HIDDEN_FIELDS.has(key);
}

function Block({ title, data }: { title: string; data: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(data ?? {}).filter(([k]) => shown(k));
  return (
    <section className="card stack" aria-label={title}>
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <EmptyState compact>{T.case.none}</EmptyState>
      ) : (
        <DefinitionList items={entries.map(([k, v]) => [caseFieldLabel(k), fieldValue(caseFieldValue(k, v))])} />
      )}
    </section>
  );
}

function ListBlock({ title, rows, block }: { title: string; rows: Record<string, unknown>[]; block?: FieldBlock }) {
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter(shown);
  return (
    <section className="card stack" aria-label={title}>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <EmptyState compact>{T.case.none}</EmptyState>
      ) : (
        <DataTable
          caption={title}
          rows={rows.map((r, i) => ({ r, i }))}
          rowKey={(row) => String(row.i)}
          columns={keys.map((k, n) => ({
            key: k,
            header: caseFieldLabel(k),
            primary: n === 0,
            cell: (row: { r: Record<string, unknown>; i: number }) => fieldValue(caseFieldValue(k, row.r[k], block)),
          }))}
        />
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
    <div className={`stack ${s.details}`}>
      <Block title={T.case.identity} data={{ ...c.identity, court: c.court?.name ?? null, est_code: c.court?.est_code ?? null }} />
      <Block title={T.case.statusBlock} data={c.status} />
      <Block title={T.case.classification} data={{ ...c.classification, ...(bench ? { sitting_bench: bench.bench_name, judges: bench.judge_names } : {}) }} />
      <Block title={T.case.place} data={c.place} />
      <Block title={T.case.asPrinted} data={c.parties_as_printed} />
      <ListBlock title={T.case.acts} rows={c.acts} />
      <ListBlock title={T.case.lowerCourts} rows={c.lower_courts} block="lower_courts" />
      <ListBlock title={T.case.applications} rows={c.applications} block="applications" />
      <ListBlock title={T.case.objections} rows={c.objections} />
      <ListBlock title={T.case.courtTransfers} rows={c.court_transfers} />
      <ListBlock title={T.case.writInfo} rows={c.writ_info} />
      <Block title={T.case.portal} data={c.portal} />
    </div>
  );
}

/** The identity and classification fields only (design portal-ui-redesign, decision 7: the claim modal's "Case
 * details" tab), with the same labels and label width as the Details tab. */
export function IdentityDetails({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const c = query.data;
  return (
    <div className={`stack ${s.details}`}>
      <Block title={T.case.identity} data={{ ...c.identity, court: c.court?.name ?? null, est_code: c.court?.est_code ?? null }} />
      <Block title={T.case.classification} data={c.classification} />
    </div>
  );
}
