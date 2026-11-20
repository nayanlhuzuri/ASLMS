"use client";

/**
 * The export dialog (design state-insights, decisions 27 and 33): the owner's 33 fields in four groups with the defaults
 * ticked, plus Applications Pending while interlocutory applications are counted inside their main case. Link to the
 * Case Page appears only for Excel. The dialog says how many cases will be exported and, for a PDF above the limit,
 * that only the first 2,000 are printed. The choice of fields is kept in this browser (`localStorage`), never on the
 * server. Download is a plain link carrying exactly the filters and sort of the list; the API builds the file and
 * writes the `insights.exported` audit row.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, Button, buttonClass, CheckField, Dialog, ErrorBanner, Loading, Notice, SegmentedField } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { InsightsField } from "@/lib/api/types";
import {
  exportHref,
  includeIaOf,
  PDF_ROW_LIMIT,
  saveFields,
  savedFields,
  type ExportFormat,
} from "@/lib/insights";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import s from "./insights.module.css";

const X = T.insights.exporting;
const GROUP_ORDER = ["identity", "parties", "court", "work"] as const;
export const APPLICATIONS_FIELD = "applications_pending";

/** The fields to tick: the kept choice (only keys the registry still has), else the registry's defaults. */
export function initialFields(registry: readonly InsightsField[], kept: string[] | null): string[] {
  const known = new Set(registry.filter((f) => f.key !== APPLICATIONS_FIELD).map((f) => f.key));
  const fromKept = (kept ?? []).filter((k) => known.has(k));
  if (fromKept.length > 0) return fromKept;
  return registry.filter((f) => f.default && f.key !== APPLICATIONS_FIELD).map((f) => f.key);
}

/** The fields sent for a format, in the registry's order: Excel-only fields are dropped for a PDF. */
export function fieldsFor(registry: readonly InsightsField[], chosen: readonly string[], format: ExportFormat): string[] {
  const set = new Set(chosen);
  return registry.filter((f) => set.has(f.key) && f.key !== APPLICATIONS_FIELD && !(f.excel_only && format !== "xlsx")).map((f) => f.key);
}

export function ExportDialog({
  format: initialFormat,
  params,
  total,
  onClose,
}: {
  format: ExportFormat;
  params: Params;
  total: number;
  onClose: () => void;
}) {
  const fields = useQuery({
    queryKey: ["insights", "fields"],
    queryFn: ({ signal }) => api<InsightsField[]>("/insights/fields", { signal }),
    staleTime: 60 * 60_000,
  });
  const [format, setFormat] = useState<ExportFormat>(initialFormat);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const registry = fields.data ?? [];
  const ticked = chosen ?? (fields.data ? initialFields(registry, savedFields()) : []);
  const sent = fieldsFor(registry, ticked, format);
  const href = exportHref(params, format, sent, params.sort);
  const iaInside = !includeIaOf(params);

  function toggle(key: string, on: boolean) {
    setChosen(on ? [...ticked.filter((k) => k !== key), key] : ticked.filter((k) => k !== key));
  }

  return (
    <Dialog
      open
      title={X.title}
      onClose={onClose}
      wide
      footer={
        <div className={s.footer}>
          <Button variant="secondary" onClick={onClose}>
            {X.cancelButton}
          </Button>
          {sent.length > 0 ? (
            <a
              className={buttonClass("primary")}
              data-variant="primary"
              href={href}
              download
              onClick={() => {
                saveFields(ticked);
                onClose();
              }}
            >
              {X.downloadButton}
            </a>
          ) : (
            <Button variant="primary" disabled title={X.noFieldsError}>
              {X.downloadButton}
            </Button>
          )}
        </div>
      }
    >
      <div className="stack">
        <SegmentedField
          label={X.formatLabel}
          options={(["xlsx", "pdf"] as const).map((k) => ({ value: k, label: X.formats[k]! }))}
          value={format}
          onChange={(v) => setFormat(v as ExportFormat)}
        />
        <p>{X.rowsNote(total)}</p>
        {format === "pdf" && total > PDF_ROW_LIMIT ? <Notice tone="warning">{X.pdfLimitNote(PDF_ROW_LIMIT, total)}</Notice> : null}
        {fields.isPending ? <Loading /> : null}
        <ErrorBanner error={fields.error} onRetry={() => void fields.refetch()} />
        {fields.data ? (
          <>
            <div>
              <Button variant="ghost" onClick={() => setChosen(initialFields(registry, null))}>
                {X.defaultsButton}
              </Button>
            </div>
            <div className={s.fieldGroups} role="group" aria-label={X.fieldsLabel}>
              {GROUP_ORDER.map((g) => {
                const items = registry.filter((f) => f.group === g && f.key !== APPLICATIONS_FIELD);
                if (items.length === 0) return null;
                return (
                  <fieldset key={g} className={s.fieldGroup}>
                    <legend>{X.groups[g]}</legend>
                    <div className={s.fieldList}>
                      {items
                        .filter((f) => !(f.excel_only && format !== "xlsx"))
                        .map((f) => (
                          <CheckField
                            key={f.key}
                            label={
                              <>
                                {f.number ? `${f.number}. ` : ""}
                                {f.label}
                                {f.excel_only ? (
                                  <>
                                    {" "}
                                    <Badge>{X.excelOnlyBadge}</Badge>
                                  </>
                                ) : null}
                              </>
                            }
                            checked={ticked.includes(f.key)}
                            onChange={(e) => toggle(f.key, e.target.checked)}
                          />
                        ))}
                      {g === "work" && iaInside ? (
                        <CheckField label={X.applicationsLabel} hint={X.applicationsHint} checked disabled readOnly />
                      ) : null}
                    </div>
                  </fieldset>
                );
              })}
            </div>
            {sent.length === 0 ? <Notice tone="warning">{X.noFieldsError}</Notice> : null}
            <p className="muted">{X.auditNote}</p>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}
