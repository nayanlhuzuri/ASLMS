"use client";

/**
 * The audit log filters (design portal-audit-health, decision 4): Person and "Name contains", Case, Office (a
 * department, then a unit inside it), Action (grouped, with "All … actions" per group), Period with quick choices,
 * and "More filters" (about the user, record type, record id). The browser checks only the name length, the date
 * order and the record id's shape; the API's refusals arrive in `apiErrors` and show under their fields. "Search"
 * hands the non-empty filters to the page, which writes them to the URL.
 */
import { useState, type FormEvent } from "react";

import { Button, SelectField, TextField, type Option } from "@/components/ui";
import { useDepartmentPeople, useDepartments } from "@/lib/api/hooks";
import {
  actionGroups,
  checkFilters,
  choiceOf,
  PERIOD_CHOICES,
  periodChoice,
  type ErrorField,
  type FilterProblems,
  type PeriodChoice,
} from "@/lib/audit";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import s from "./audit.module.css";

export function AuditFilters({
  params,
  today,
  actions,
  apiErrors,
  initialProblems,
  busy,
  onSearch,
  onClear,
  onRefresh,
}: {
  /** The URL's filters, as sent to the API. */
  params: Params;
  today: string;
  /** The codes of `GET /audit/actions` (none while loading). */
  actions: readonly string[];
  /** The API's refusal of the search shown, by field. */
  apiErrors: Partial<Record<ErrorField, string>>;
  /** The browser's problems with the URL's own filters (a link typed by hand). */
  initialProblems?: FilterProblems | null;
  busy?: boolean;
  onSearch: (next: Params) => void;
  onClear: () => void;
  onRefresh: () => void;
}) {
  const [form, setForm] = useState({
    user: params.user ?? "",
    actor: params.actor ?? "",
    case: params.case ?? "",
    action: params.action ?? "",
    about_user: params.about_user ?? "",
    entity_type: params.entity_type ?? "",
    entity_id: params.entity_id ?? "",
  });
  const [department, setDepartment] = useState(params.office ?? "");
  const [unit, setUnit] = useState("");
  const [choice, setChoice] = useState<PeriodChoice>(() => choiceOf(params.from, params.to, today));
  const [from, setFrom] = useState(params.from ?? "");
  const [to, setTo] = useState(params.to ?? "");
  const [problems, setProblems] = useState<FilterProblems | null>(initialProblems ?? null);
  // the API's refusal concerns the search shown; once a field is changed its own message goes
  const [touched, setTouched] = useState<Set<string>>(new Set());

  const departments = useDepartments();
  const deptList = departments.data?.departments ?? [];
  const known = deptList.some((d) => d.code === department);
  const people = useDepartmentPeople(known ? department : null);
  const units = people.data?.units ?? [];

  const set = (name: keyof typeof form | "office" | "period", patch: Partial<typeof form> = {}) => {
    setForm((f) => ({ ...f, ...patch }));
    setTouched((t) => new Set(t).add(name));
  };

  function submit(e: FormEvent) {
    e.preventDefault();
    const period = choice === "custom" ? { from, to } : (periodChoice(choice, today) ?? { from: "", to: "" });
    const found = checkFilters({ actor: form.actor, from: period.from, to: period.to, entity_id: form.entity_id }, today);
    setProblems(found);
    if (found) return;
    const next: Params = {};
    for (const [k, v] of Object.entries(form)) if (v.trim()) next[k] = v.trim();
    const office = unit || department;
    if (office) next.office = office;
    if (period.from) next.from = period.from;
    if (period.to) next.to = period.to;
    onSearch(next);
  }

  const apiError = (field: ErrorField) => (touched.has(field) ? undefined : apiErrors[field]);

  const deptOptions: Option[] = deptList.map((d) => ({ value: d.code, label: `${d.name} (${d.code})` }));
  if (department && !known) deptOptions.push({ value: department, label: department });

  const groups = actionGroups(actions, T.audit.groups);
  const actionOptions = groups.map((g) => ({
    label: g.label,
    options: [
      ...(g.prefix ? [{ value: g.prefix, label: T.audit.allActions(g.label) }] : []),
      ...g.codes.map((c) => ({ value: c, label: c })),
    ],
  }));
  const listed = actionOptions.some((g) => g.options.some((o) => o.value === form.action));
  const extraAction: Option[] = form.action && !listed ? [{ value: form.action, label: form.action }] : [];

  const periodProblem = problems?.period ? T.audit.periodProblems[problems.period] : apiError("period");
  const moreOpen = !!(params.about_user || params.entity_type || params.entity_id || problems?.entity_id);

  return (
    <form className={s.form} onSubmit={submit} aria-label={T.audit.form} noValidate>
      <TextField
        label={T.audit.person}
        hint={T.audit.personHint}
        value={form.user}
        autoComplete="off"
        onChange={(e) => set("user", { user: e.target.value })}
        error={apiError("user")}
      />
      <TextField
        label={T.audit.actor}
        hint={T.audit.actorHint}
        value={form.actor}
        maxLength={100}
        onChange={(e) => set("actor", { actor: e.target.value })}
        error={problems?.actor ? T.audit.actorProblem : apiError("actor")}
      />
      <TextField
        label={T.audit.case}
        hint={T.audit.caseHint}
        value={form.case}
        className="mono"
        onChange={(e) => set("case", { case: e.target.value })}
        error={apiError("case")}
      />
      <SelectField
        label={T.audit.office}
        hint={T.audit.officeHint}
        value={department}
        onChange={(e) => {
          setDepartment(e.target.value);
          setUnit("");
          set("office");
        }}
        options={[{ value: "", label: T.audit.anyOffice }, ...deptOptions]}
        error={apiError("office")}
      />
      {known ? (
        <SelectField
          label={T.audit.unit}
          value={unit}
          onChange={(e) => {
            setUnit(e.target.value);
            set("office");
          }}
          options={[
            { value: "", label: T.audit.wholeDepartment },
            ...units.map((u) => ({ value: u.code, label: `${u.name} (${u.code})` })),
          ]}
        />
      ) : null}
      <SelectField
        label={T.audit.action}
        value={form.action}
        onChange={(e) => set("action", { action: e.target.value })}
        options={[{ value: "", label: T.audit.anyAction }, ...extraAction]}
        groups={actionOptions}
      />
      <SelectField
        label={T.audit.period}
        value={choice}
        onChange={(e) => {
          setChoice(e.target.value as PeriodChoice);
          setProblems((p) => (p ? { ...p, period: undefined } : p));
          set("period");
        }}
        options={PERIOD_CHOICES.map((c) => ({ value: c, label: T.audit.choices[c] ?? c }))}
        error={choice === "custom" ? undefined : periodProblem}
      />
      {choice === "custom" ? (
        <>
          <TextField
            label={T.audit.from}
            type="date"
            value={from}
            max={today}
            onChange={(e) => {
              setFrom(e.target.value);
              set("period");
            }}
          />
          <TextField
            label={T.audit.to}
            type="date"
            value={to}
            max={today}
            onChange={(e) => {
              setTo(e.target.value);
              set("period");
            }}
            error={periodProblem}
          />
        </>
      ) : null}
      <details className={s.more} open={moreOpen || undefined}>
        <summary>{T.audit.more}</summary>
        <div className={s.moreFields}>
          <TextField
            label={T.audit.aboutUser}
            hint={T.audit.aboutUserHint}
            value={form.about_user}
            autoComplete="off"
            onChange={(e) => set("about_user", { about_user: e.target.value })}
            error={apiError("about_user")}
          />
          <TextField
            label={T.audit.entityType}
            value={form.entity_type}
            maxLength={60}
            onChange={(e) => set("entity_type", { entity_type: e.target.value })}
          />
          <TextField
            label={T.audit.entityId}
            value={form.entity_id}
            className="mono"
            onChange={(e) => set("entity_id", { entity_id: e.target.value })}
            error={problems?.entity_id ? T.audit.entityIdProblem : undefined}
          />
        </div>
      </details>
      <div className={s.actions}>
        <Button type="submit">{T.audit.search}</Button>
        <Button variant="secondary" onClick={onClear}>
          {T.audit.clear}
        </Button>
        <Button variant="secondary" onClick={onRefresh} busy={busy}>
          {T.audit.refresh}
        </Button>
      </div>
    </form>
  );
}
