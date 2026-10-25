"use client";

/**
 * The choices above a report (design portal-reports, decisions 3-6): the scope ("Whole State" or a department), the
 * period with its quick choices, the holder department and "List the files". "Show report" hands the parameters to
 * the page, which writes them to the URL. The browser checks only that both dates are given, in order and not after
 * today; the range limits are the server's and its refusal is shown under the period fields.
 */
import { useState, type FormEvent } from "react";

import { Button, CheckField, SelectField, TextField } from "@/components/ui";
import type { ReportCatalogueItem, ReportDepartment } from "@/lib/api/types";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import {
  checkPeriod,
  choiceOf,
  departmentLabel,
  PERIOD_CHOICES,
  periodChoice,
  type PeriodChoice,
  type ReportKey,
} from "@/lib/reports";

import s from "./reports.module.css";

export function ReportForm({
  reportKey,
  item,
  departments,
  holders,
  params,
  today,
  periodError,
  busy,
  onShow,
  onRefresh,
}: {
  reportKey: ReportKey;
  item: ReportCatalogueItem;
  departments: readonly ReportDepartment[];
  /** Every active department, for the holder department (a file may be sent to any department). */
  holders: { code: string; name: string }[];
  params: Params;
  today: string;
  /** The API's message for a refused period. */
  periodError?: string | null;
  busy?: boolean;
  onShow: (next: Params) => void;
  onRefresh: () => void;
}) {
  const hasPeriod = reportKey === "hearings-disposals" || reportKey === "data-health";
  const stateScope = item.scopes.includes("state");
  const [department, setDepartment] = useState(params.department ?? (stateScope ? "" : (item.departments[0] ?? "")));
  const [choice, setChoice] = useState<PeriodChoice>(() =>
    reportKey === "hearings-disposals" && !params.from && !params.to
      ? "this_month"
      : choiceOf(reportKey, params.from, params.to, today),
  );
  const [from, setFrom] = useState(params.from ?? "");
  const [to, setTo] = useState(params.to ?? "");
  const [holder, setHolder] = useState(params.holder_department ?? "");
  const [includeCases, setIncludeCases] = useState(params.include_cases === "true");
  const [problem, setProblem] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const next: Params = {};
    if (reportKey !== "data-health" && department) next.department = department;
    if (hasPeriod) {
      if (choice === "custom") {
        const bad = checkPeriod(from || undefined, to || undefined, today);
        if (bad) {
          setProblem(T.reports.periodProblems[bad] ?? bad);
          return;
        }
        next.from = from;
        next.to = to;
      } else if (!(reportKey === "data-health" && choice === "last_7")) {
        const p = periodChoice(choice, today)!;
        next.from = p.from;
        next.to = p.to;
      }
    }
    if (reportKey === "pending-actions") {
      if (holder) next.holder_department = holder;
      if (includeCases) next.include_cases = "true";
    }
    setProblem(null);
    onShow(next);
  }

  const options = item.departments.map((code) => {
    const d = departments.find((x) => x.code === code);
    const label = departmentLabel(code, departments);
    return { value: code, label: d && !d.is_active ? `${label} — ${T.reports.inactive}` : label };
  });
  const shownError = problem ?? periodError ?? null;
  const choices = hasPeriod ? PERIOD_CHOICES[reportKey as "hearings-disposals" | "data-health"] : [];

  return (
    <form className={s.form} onSubmit={submit} aria-label={T.reports.form} noValidate>
      {reportKey === "data-health" ? null : stateScope || item.departments.length > 1 ? (
        <SelectField
          label={stateScope ? T.reports.scope : T.reports.department}
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          options={stateScope ? [{ value: "", label: T.reports.wholeState }, ...options] : options}
        />
      ) : item.departments.length === 1 ? (
        <p>
          {T.reports.department}: {departmentLabel(item.departments[0]!, departments)}
        </p>
      ) : null}
      {hasPeriod ? (
        <SelectField
          label={T.reports.period}
          value={choice}
          onChange={(e) => {
            setChoice(e.target.value as PeriodChoice);
            setProblem(null);
          }}
          options={choices.map((c) => ({ value: c, label: T.reports.choices[c] ?? c }))}
          error={choice === "custom" ? undefined : shownError}
        />
      ) : null}
      {hasPeriod && choice === "custom" ? (
        <>
          <TextField label={T.reports.from} type="date" value={from} max={today} onChange={(e) => setFrom(e.target.value)} />
          <TextField
            label={T.reports.to}
            type="date"
            value={to}
            max={today}
            onChange={(e) => setTo(e.target.value)}
            error={shownError}
          />
        </>
      ) : null}
      {reportKey === "pending-actions" ? (
        <>
          <SelectField
            label={T.reports.holder}
            value={holder}
            onChange={(e) => setHolder(e.target.value)}
            options={[
              { value: "", label: T.reports.allHolders },
              ...holders.map((d) => ({ value: d.code, label: `${d.name} (${d.code})` })),
            ]}
            hint={T.reports.holderHint}
          />
          <div>
            <CheckField
              inline
              label={T.reports.listFiles}
              checked={includeCases}
              onChange={(e) => setIncludeCases(e.target.checked)}
            />
            <span className="muted">{T.reports.listFilesHint}</span>
          </div>
        </>
      ) : null}
      <div className={s.actions}>
        <Button type="submit">{T.reports.show}</Button>
        <Button variant="secondary" onClick={onRefresh} busy={busy}>
          {T.reports.refresh}
        </Button>
      </div>
    </form>
  );
}
