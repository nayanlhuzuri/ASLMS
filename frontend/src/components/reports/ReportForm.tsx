"use client";

/**
 * The choices above a report (design portal-reports, decisions 3-6): the scope ("Whole State" or a department), the
 * period with its quick choices, the holder department and "List the files". "Show report" hands the parameters to
 * the page, which writes them to the URL. The browser checks only that both dates are given, in order and not after
 * today; the range limits are the server's and its refusal is shown under the period fields. Filter Layout B (design
 * portal-ui-polish-2, decision 23): the period, or "As Of" today for a report without one, is the card's hero; the
 * scope, the holder department and "List the cases" sit on the right with Show Report and Refresh; the report's scope
 * line is the summary strip; the downloads stay in the page header.
 */
import { useState, type ReactNode } from "react";

import { Button, CheckField, FilterCard, OfficePicker, SelectField, TextField } from "@/components/ui";
import type { OfficeChoice, ReportCatalogueItem, ReportDepartment } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
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

/** The departments as Office Picker options: one level, no call (departments only). */
export function holderChoices(holders: { code: string; name: string; kind?: string | null }[]): OfficeChoice[] {
  return holders.map((d) => ({
    code: d.code,
    name: d.name,
    kind: d.kind ?? "department",
    tier: "department",
    depth: 1,
    parent_code: null,
    ancestors: [],
    is_active: true,
  }));
}

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
  summary,
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
  /** The summary strip: the scope line of the report on screen. */
  summary?: ReactNode;
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

  function submit() {
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

  // design portal-ui-polish-2, decision 23: Layout B; the period (or "As Of" for a report without one) is the hero
  const hero = hasPeriod ? (
    <div className={s.heroFields}>
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
      {choice === "custom" ? (
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
    </div>
  ) : (
    <div className={s.asOf}>
      <span className={s.asOfCaption}>{T.reports.asOf}</span>
      <span className={s.asOfDate}>{formatDate(today)}</span>
      <span className={s.asOfNote}>{T.reports.asOfNote}</span>
    </div>
  );

  return (
    <FilterCard
      label={T.reports.form}
      hero={hero}
      onSubmit={submit}
      submitLabel={T.reports.show}
      actions={
        <Button variant="secondary" onClick={onRefresh} busy={busy}>
          {T.reports.refresh}
        </Button>
      }
      summary={summary}
    >
      {reportKey === "data-health" ? null : stateScope || item.departments.length > 1 ? (
        <SelectField
          label={stateScope ? T.reports.scope : T.reports.department}
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          options={stateScope ? [{ value: "", label: T.reports.wholeState }, ...options] : options}
        />
      ) : item.departments.length === 1 ? (
        <p className={s.fixedScope}>
          {T.reports.department}: {departmentLabel(item.departments[0]!, departments)}
        </p>
      ) : null}
      {reportKey === "pending-actions" ? (
        <>
          {/* design portal-ui-polish-2, decision 30: the Office Picker over the departments the page already holds */}
          <OfficePicker
            label={T.reports.holder}
            options={holderChoices(holders)}
            placeholder={T.reports.allHoldersPlaceholder}
            value={holder || null}
            onChange={(code) => setHolder(code ?? "")}
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
    </FilterCard>
  );
}
