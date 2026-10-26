"use client";

/**
 * The audit log filters (design portal-audit-health, decision 4): Person and "Name contains", Case, Office (a
 * department, then a unit inside it), Action (grouped, with "All … actions" per group), the period, and "More filters"
 * (the unit, about the user, record type, record id). The browser checks only the name length, the date order and the
 * record id's shape; the API's refusals arrive in `apiErrors` and show under their fields. "Search" hands the
 * non-empty filters to the page, which writes them to the URL.
 *
 * Filter Layout B (design portal-ui-polish-2, decision 23): the period is the card's hero, From and To with the quick
 * choices Today, 7 Days and 30 Days (IST days, today included); Person, Name Contains, Case, Office (the Office Picker)
 * and Action on the right with Search, Clear and Refresh; Unit, About the User, Record Type and Record ID under More
 * Filters; the summary strip says "Newest First" (the API is cursor-paged, so there is no total) and shows the applied
 * filters as chips, each removable, with Clear All.
 */
import { useState } from "react";

import { FilterChips } from "@/components/filters/FilterChips";
import { Button, FilterCard, OfficePicker, SelectField, TextField, type Option } from "@/components/ui";
import { useDepartmentPeople, useDepartments } from "@/lib/api/hooks";
import {
  actionGroups,
  actionName,
  checkFilters,
  periodChoice,
  type ErrorField,
  type FilterProblems,
  type PeriodChoice,
} from "@/lib/audit";
import type { Chip } from "@/lib/filters";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import s from "./audit.module.css";

/** The quick choices of the period (decision 23). */
const QUICK: PeriodChoice[] = ["today", "last_7", "last_30"];

/** The applied filters of the URL as chips (each removes its own keys). */
export function auditChips(params: Params): Chip[] {
  const out: Chip[] = [];
  const add = (keys: string[], label: string, value: string | undefined) => {
    if (value) out.push({ keys, label: `${label}: ${value}` });
  };
  add(["user"], T.audit.person, params.user);
  add(["actor"], T.audit.actor, params.actor);
  add(["case"], T.audit.case, params.case);
  if (params.office) {
    out.push({
      keys: ["office", "office_subtree"],
      label: `${T.audit.office}: ${params.office}${params.office_subtree === "false" ? "" : ` ${T.officePicker.subMarker}`}`,
    });
  }
  add(["action"], T.audit.action, params.action ? actionName(params.action) : undefined);
  if (params.from || params.to) {
    out.push({ keys: ["from", "to"], label: `${T.audit.period}: ${params.from ?? "…"} – ${params.to ?? "…"}` });
  }
  add(["about_user"], T.audit.aboutUser, params.about_user);
  add(["entity_type"], T.audit.entityType, params.entity_type);
  add(["entity_id"], T.audit.entityId, params.entity_id);
  return out;
}

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
  const [subtree, setSubtree] = useState(params.office_subtree !== "false");
  const [unit, setUnit] = useState("");
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

  function setPeriod(nextFrom: string, nextTo: string) {
    setFrom(nextFrom);
    setTo(nextTo);
    setProblems((p) => (p ? { ...p, period: undefined } : p));
    set("period");
  }

  function submit() {
    const found = checkFilters({ actor: form.actor, from, to, entity_id: form.entity_id }, today);
    setProblems(found);
    if (found) return;
    const next: Params = {};
    for (const [k, v] of Object.entries(form)) if (v.trim()) next[k] = v.trim();
    const office = unit || department;
    if (office) next.office = office;
    if (office && !subtree) next.office_subtree = "false";
    if (from) next.from = from;
    if (to) next.to = to;
    onSearch(next);
  }

  const apiError = (field: ErrorField) => (touched.has(field) ? undefined : apiErrors[field]);

  const groups = actionGroups(actions, T.audit.groups);
  const actionOptions = groups.map((g) => ({
    label: g.label,
    options: [
      ...(g.prefix ? [{ value: g.prefix, label: T.audit.allActions(g.label) }] : []),
      ...g.codes.map((c) => ({ value: c, label: actionName(c) })),
    ],
  }));
  const listed = actionOptions.some((g) => g.options.some((o) => o.value === form.action));
  const extraAction: Option[] = form.action && !listed ? [{ value: form.action, label: form.action }] : [];

  const periodProblem = problems?.period ? T.audit.periodProblems[problems.period] : apiError("period");
  const moreCount = [params.about_user, params.entity_type, params.entity_id].filter(Boolean).length;
  const chips = auditChips(params);

  const hero = (
    <fieldset className={s.period}>
      <legend className={s.periodLegend}>{T.audit.period}</legend>
      <TextField
        label={T.audit.from}
        type="date"
        value={from}
        max={today}
        onChange={(e) => setPeriod(e.target.value, to)}
      />
      <TextField label={T.audit.to} type="date" value={to} max={today} onChange={(e) => setPeriod(from, e.target.value)} error={periodProblem} />
      <div className={s.quick} role="group" aria-label={T.audit.quickPeriods}>
        {QUICK.map((c) => {
          const p = periodChoice(c, today)!;
          const on = p.from === from && p.to === to;
          return (
            <Button key={c} variant="secondary" aria-pressed={on} onClick={() => setPeriod(p.from, p.to)}>
              {T.audit.quick[c]}
            </Button>
          );
        })}
        {from || to ? (
          <Button variant="link" onClick={() => setPeriod("", "")}>
            {T.audit.choices.any}
          </Button>
        ) : null}
      </div>
    </fieldset>
  );

  return (
    <FilterCard
      label={T.audit.form}
      hero={hero}
      onSubmit={submit}
      submitLabel={T.audit.search}
      actions={
        <>
          <Button variant="secondary" onClick={onClear}>
            {T.audit.clear}
          </Button>
          <Button variant="secondary" onClick={onRefresh} busy={busy}>
            {T.audit.refresh}
          </Button>
        </>
      }
      moreCount={moreCount}
      moreOpen={moreCount > 0 || !!problems?.entity_id ? true : undefined}
      more={
        <>
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
        </>
      }
      summary={
        <>
          <span>{T.audit.newestFirst}</span>
          <FilterChips
            chips={chips}
            onRemove={(drop) => {
              const rest: Params = { ...params };
              for (const k of drop) delete rest[k];
              onSearch(rest);
            }}
            onClearAll={onClear}
          />
        </>
      }
    >
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
      {/* design portal-ui-polish-2, decision 30: the Office Picker (purpose audit, inactive offices marked) with
          Include Sub-offices, sent as office_subtree */}
      <OfficePicker
        label={T.audit.office}
        hint={T.audit.officeHint}
        purpose="audit"
        includeInactive
        placeholder={T.audit.anyOfficePlaceholder}
        value={department || null}
        onChange={(code) => {
          setDepartment(code ?? "");
          setUnit("");
          set("office");
        }}
        subtree={{
          value: subtree,
          onChange: (v) => {
            setSubtree(v);
            set("office");
          },
        }}
        error={apiError("office")}
      />
      <SelectField
        label={T.audit.action}
        value={form.action}
        onChange={(e) => set("action", { action: e.target.value })}
        options={[{ value: "", label: T.audit.anyAction }, ...extraAction]}
        groups={actionOptions}
      />
    </FilterCard>
  );
}
