"use client";

/**
 * The one filter bar of every case list (design portal-filters, decisions 9-14): the shared fields the list declares in
 * `LIST_FILTERS` plus the list's own controls, in one form that applies with "Apply" (Enter in any field submits), so
 * a date range is never half-applied. First row: Words, Cause-list date, Next hearing, Case type and the list's main
 * own controls; "More filters" (open whenever one of its fields is set): Year, Status, Court, Bench, the department
 * field and the remaining own controls. Under the form: one chip per applied filter with "Clear all", and the filtered
 * total. Filters live in the query string (`useFilters`, which also resets the page offset); the API checks every value
 * again and its message shows if one still comes back.
 *
 * `layout="card"` (design portal-ui-polish-2, decision 22) draws the same form as the kit's `FilterCard` (Filter
 * Layout B): the `hero` field (a shared field key or an own control's key) in the left zone, the first-row fields in
 * the right zone with Search and More Filters (n), the "More filters" fields in the card's panel, and the total, the
 * chips and the note in the summary strip. The URL keys, the chips, the validation and the legacy keys are the bar's.
 */
import { Fragment, useId, useState, type ReactNode } from "react";

import { useFilters } from "@/components/inbox/common";
import { Button, CheckField, FilterCard, SegmentedField, SelectField, TextField, type Option } from "@/components/ui";
import { useBenches, useCaseTypes, useDepartments } from "@/lib/api/hooks";
import {
  CASE_STATUSES,
  checkChip,
  checkIsOn,
  checkValue,
  chipsOf,
  dateModeOf,
  dateParams,
  FIELD_KEYS,
  legacyParams,
  LIST_FILTERS,
  LISTED_PRESETS,
  moreFieldsOf,
  NEXT_PRESETS,
  validate,
  type Chip,
  type ListKey,
  type SharedField,
} from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import { DateRangeField, type DateValue } from "./DateRangeField";
import { clearAllUpdates } from "./NoCaseMatches";
import { FilterChips } from "./FilterChips";
import s from "./filters.module.css";

/** A list's own control, drawn in the same form (decision 9). `more` puts it under "More filters"; `first` draws it
 * right after Words, before the date fields (Department cases' Unit, Officer and Stage). A `defaultOn` check is ticked
 * unless the URL says `"false"`; its chip shows only the unticked state, as `offLabel` (design ownership-refinements,
 * decision 8). */
export type OwnControl =
  | { key: string; kind: "select"; label: string; options: Option[]; placeholder?: string; more?: boolean; first?: boolean }
  | {
      key: string;
      kind: "check";
      label: string;
      more?: boolean;
      first?: boolean;
      defaultOn?: boolean;
      offLabel?: string;
    }
  | { key: string; kind: "text" | "number" | "date"; label: string; more?: boolean; step?: string; first?: boolean }
  /** A choice applied at once, without a chip (design case-workspace-admin, decision 17); "" is the default. */
  | { key: string; kind: "segmented"; label: string; options: Option[]; more?: boolean; first?: boolean };

export interface FilterBarProps {
  list: ListKey;
  params: Params;
  own?: OwnControl[];
  /** Pairs of own date keys checked like a range (`[from, to]`). */
  ownRanges?: [string, string][];
  /** The filtered total of the list ("128 cases match"); hidden while unknown. */
  total?: number | null;
  noun?: string;
  /** The department choices of `owner` (default: every active department). */
  ownerOptions?: Option[];
  wordsLabel?: string;
  /** A hint under the words box (the card's hero, where the label is short). */
  wordsHint?: string;
  /** A line under the chips (the Alerts list's case-less note). */
  note?: ReactNode;
  /** `card`: Filter Layout B, the kit's `FilterCard` (design portal-ui-polish-2, decision 22). */
  layout?: "bar" | "card";
  /** With `layout="card"`: the left zone's field, a shared field key or an own control's key. */
  hero?: string;
  /** The shared fields under "More filters" on this page (default: the list's). */
  more?: readonly SharedField[];
  /** With `layout="card"`: the page's own count line at the head of the summary strip (in place of `total`). */
  countLine?: ReactNode;
}

function presetOptions(kind: "listed" | "next", list: ListKey): Option[] {
  const labels = kind === "listed" ? T.filters.listedPresets : T.filters.nextPresets;
  const presets: readonly string[] = kind === "listed" ? LISTED_PRESETS : NEXT_PRESETS;
  const choices = kind === "next" ? LIST_FILTERS[list].nextChoices : undefined;
  if (choices) {
    // design portal-ui-redesign, decision 5: Department cases' Next hearing (Any date, This week, Next 30 days,
    // Choose dates)
    return choices.map((value) => ({ value, label: T.inbox.departmentNext[value] ?? labels[value] ?? value }));
  }
  return ["", ...presets, "date", "range"].map((value) => ({ value, label: labels[value] ?? value }));
}

const FIELD_LABELS: Record<SharedField, string> = {
  q: T.filters.words,
  listed: T.filters.listed,
  next: T.filters.next,
  case_type: T.filters.caseType,
  year: T.filters.year,
  case_status: T.filters.status,
  court_no: T.filters.court,
  bench: T.filters.bench,
  owner: T.filters.owner,
  scored_for: T.filters.scoredFor,
  other_office: T.filters.otherOffice,
  next_differs: T.filters.nextDiffers,
};

const CHIP_LABELS: Record<SharedField, string> = { ...FIELD_LABELS, ...T.filters.chipNames };

/** The order the shared fields are drawn in, on the first row and under "More filters". */
const FIELD_ORDER: SharedField[] = [
  "q",
  "listed",
  "next",
  "case_type",
  "year",
  "case_status",
  "court_no",
  "bench",
  "owner",
  "scored_for",
  "other_office",
  "next_differs",
];

function ownChips(params: Params, own: OwnControl[]): Chip[] {
  const out: Chip[] = [];
  for (const c of own) {
    const v = params[c.key];
    if (c.kind === "check") {
      const chip = checkChip(c.key, v, c);
      if (chip) out.push(chip);
      continue;
    }
    if (!v || c.kind === "segmented") continue;
    const text = c.kind === "select" ? (c.options.find((o) => o.value === v)?.label ?? v) : v;
    out.push({ keys: [c.key], label: `${c.label}: ${text}` });
  }
  return out;
}

/** The URL keys the bar writes: the shared fields' keys, the own controls and the old names it replaces. */
function managedKeys(list: ListKey, own: OwnControl[]): string[] {
  const cfg = LIST_FILTERS[list];
  return [...cfg.fields.flatMap((f) => FIELD_KEYS[f]), ...own.map((c) => c.key), ...Object.keys(cfg.legacy ?? {})];
}

export function FilterBar(props: FilterBarProps) {
  const { list, params, own = [], total, noun = "cases", note, layout = "bar", hero } = props;
  const setFilters = useFilters(params);
  const [userOpen, setUserOpen] = useState(false);
  const cfg = LIST_FILTERS[list];
  const p = legacyParams(params, list);
  const hidden = cfg.hidden ?? [];
  const moreList = props.more ?? moreFieldsOf(list);
  const moreShared = cfg.fields.filter((f) => moreList.includes(f) && !hidden.includes(f) && f !== hero);
  const moreOwn = own.filter((c) => c.more && c.key !== hero);
  const setShared = moreShared.filter((f) => FIELD_KEYS[f].some((k) => !!p[k]));
  const setOwn = moreOwn.filter((c) => !!params[c.key]);
  const moreCount = setShared.length + setOwn.length;
  const open = userOpen || moreCount > 0;
  const keys = managedKeys(list, own);
  // the form is re-created when the applied filters change (a chip removed, Back), so it always shows the URL
  const signature = keys.map((k) => `${k}=${params[k] ?? ""}`).join("&");
  const chips = [
    ...chipsOf(params, list, {
      field: CHIP_LABELS,
      listedPresets: T.filters.listedPresets,
      nextPresets: T.filters.nextPresets,
      statuses: T.filters.statuses,
      range: T.filters.range,
      from: T.filters.fromOnly,
      to: T.filters.toOnly,
    }),
    ...ownChips(params, own),
  ];
  const chipRow = (
    <FilterChips
      chips={chips}
      onRemove={(drop) => setFilters(Object.fromEntries(drop.map((k) => [k, undefined])))}
      onClearAll={() => setFilters(clearAllUpdates(params, list))}
    />
  );
  const totalLine =
    total !== undefined && total !== null ? (
      <p className={s.total} aria-live="polite">
        {T.filters.match(formatNumber(total), T.filters.nouns[noun] ?? noun)}
      </p>
    ) : null;
  const card = layout === "card";
  const form = (
    <FilterForm
      key={signature}
      {...props}
      own={own}
      moreList={moreList}
      open={open}
      moreCount={moreCount}
      hasMore={moreShared.length + moreOwn.length > 0}
      onToggle={() => setUserOpen((o) => !o)}
      onApply={(updates) => setFilters(updates)}
      summary={
        card && (chips.length > 0 || note || totalLine || props.countLine) ? (
          <>
            {props.countLine ?? totalLine}
            {chipRow}
            {note ? <p className="muted">{note}</p> : null}
          </>
        ) : null
      }
    />
  );
  if (card) return form;
  return (
    <div className={s.bar}>
      {form}
      {chipRow}
      {note ? <p className="muted">{note}</p> : null}
      {totalLine}
    </div>
  );
}

function FilterForm({
  list,
  params,
  own = [],
  ownRanges = [],
  ownerOptions,
  wordsLabel,
  wordsHint,
  layout = "bar",
  hero,
  moreList,
  open,
  moreCount,
  hasMore,
  onToggle,
  onApply,
  summary,
}: FilterBarProps & {
  moreList: readonly SharedField[];
  open: boolean;
  moreCount: number;
  hasMore: boolean;
  onToggle: () => void;
  onApply: (updates: Params) => void;
  summary: ReactNode;
}) {
  const card = layout === "card";
  const cfg = LIST_FILTERS[list];
  const fields = new Set(cfg.fields);
  const more = new Set(moreList);
  const hidden = new Set(cfg.hidden ?? []);
  /** Where a shared field is drawn: the first row, "More filters", or nowhere (hidden). */
  const inRow = (f: SharedField) => fields.has(f) && !more.has(f) && !hidden.has(f);
  const inMore = (f: SharedField) => fields.has(f) && more.has(f) && !hidden.has(f);
  const p = legacyParams(params, list);
  const moreId = useId();
  const datalistId = useId();
  const needsDepartments =
    (fields.has("owner") && !ownerOptions) || fields.has("scored_for") || fields.has("other_office");
  const departments = useDepartments(needsDepartments);
  const caseTypes = useCaseTypes(fields.has("case_type"));
  const benches = useBenches(fields.has("court_no") || fields.has("bench"));
  const [form, setForm] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const f of cfg.fields) if (f !== "listed" && f !== "next") out[f] = p[f] ?? "";
    for (const c of own) {
      out[c.key] = c.kind === "check" ? (checkIsOn(params[c.key], c.defaultOn) ? "true" : "") : (params[c.key] ?? "");
    }
    return out;
  });
  const [dates, setDates] = useState<Record<"listed" | "next", DateValue>>(() => ({
    listed: dateModeOf(p, "listed"),
    next: dateModeOf(p, "next"),
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));

  function apply() {
    const found = validate(
      {
        q: fields.has("q") ? form.q : undefined,
        listed: fields.has("listed") ? dates.listed : undefined,
        next: fields.has("next") ? dates.next : undefined,
        year: fields.has("year") ? form.year : undefined,
        bench: fields.has("bench") ? form.bench : undefined,
        ranges: ownRanges.map(([from, to]) => ({ key: to, from: form[from] ?? "", to: form[to] ?? "" })),
      },
      {
        reversed: T.filters.reversed,
        chooseDate: T.filters.chooseDate,
        year: T.filters.badYear,
        words: T.filters.shortWords,
        bench: T.filters.badBench,
      },
    );
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const updates: Params = {};
    for (const old of Object.keys(cfg.legacy ?? {})) updates[old] = undefined;
    for (const f of cfg.fields) {
      if (f === "listed" || f === "next") {
        const d = dates[f];
        Object.assign(updates, dateParams(f, d.mode, d.from, d.to));
      } else {
        const v = (form[f] ?? "").trim();
        updates[f] = (f === "bench" ? v.replace(/\s+/g, " ") : v) || undefined;
      }
    }
    for (const c of own) {
      const v = (form[c.key] ?? "").trim();
      updates[c.key] = c.kind === "check" ? checkValue(v === "true", c.defaultOn) : v || undefined;
    }
    onApply(updates);
  }

  const departmentOptions: Option[] = (departments.data?.departments ?? []).map((d) => ({
    value: d.code,
    label: `${d.code} — ${d.name}`,
  }));
  const withCurrent = (options: Option[], current: string | undefined): Option[] =>
    current && !options.some((o) => o.value === current) ? [...options, { value: current, label: current }] : options;

  const ownControl = (c: OwnControl) => {
    if (c.kind === "segmented") {
      return (
        <SegmentedField
          key={c.key}
          label={c.label}
          options={c.options}
          value={form[c.key] ?? ""}
          onChange={(v) => {
            set(c.key, v);
            onApply({ [c.key]: v || undefined });
          }}
        />
      );
    }
    if (c.kind === "check") {
      return (
        <CheckField
          key={c.key}
          inline
          label={c.label}
          checked={form[c.key] === "true"}
          onChange={(e) => set(c.key, e.target.checked ? "true" : "")}
        />
      );
    }
    if (c.kind === "select") {
      return (
        <SelectField
          key={c.key}
          label={c.label}
          options={withCurrent(c.options, form[c.key])}
          placeholder={c.placeholder}
          value={form[c.key] ?? ""}
          onChange={(e) => set(c.key, e.target.value)}
        />
      );
    }
    return (
      <TextField
        key={c.key}
        label={c.label}
        type={c.kind}
        step={c.kind === "number" ? c.step : undefined}
        value={form[c.key] ?? ""}
        error={errors[c.key]}
        onChange={(e) => set(c.key, e.target.value)}
      />
    );
  };

  const dateField = (kind: "listed" | "next") =>
    fields.has(kind) ? (
      <DateRangeField
        key={kind}
        label={FIELD_LABELS[kind]}
        presets={presetOptions(kind, list)}
        value={dates[kind]}
        onChange={(next) => setDates((d) => ({ ...d, [kind]: next }))}
        errors={{ from: errors[`${kind}_from`], to: errors[`${kind}_to`] }}
      />
    ) : null;

  const departmentField = (field: "owner" | "scored_for" | "other_office") =>
    fields.has(field) ? (
      <SelectField
        key={field}
        label={FIELD_LABELS[field]}
        placeholder={T.filters.anyDepartment}
        options={withCurrent(field === "owner" && ownerOptions ? ownerOptions : departmentOptions, form[field])}
        value={form[field] ?? ""}
        onChange={(e) => set(field, e.target.value)}
      />
    ) : null;

  const courts = (benches.data?.court_numbers ?? []).map((c) => ({ value: c.court_no, label: T.filters.courtNo(c.court_no) }));
  const types = (caseTypes.data ?? [])
    .filter((t) => t.short_name)
    .map((t) => ({ value: t.short_name!, label: `${t.short_name}${t.full_name ? ` — ${t.full_name}` : ""}` }));

  /** One shared field's control, wherever it is drawn. */
  const sharedField = (f: SharedField): ReactNode => {
    switch (f) {
      case "q":
        return (
          <TextField
            key="q"
            label={wordsLabel ?? T.filters.words}
            hint={wordsHint}
            value={form.q ?? ""}
            error={errors.q}
            onChange={(e) => set("q", e.target.value)}
            style={card ? undefined : { minWidth: 280 }}
          />
        );
      case "listed":
      case "next":
        return dateField(f);
      case "case_type":
        return (
          <SelectField
            key="case_type"
            label={T.filters.caseType}
            placeholder={T.filters.anyCaseType}
            options={withCurrent(types, form.case_type)}
            value={form.case_type ?? ""}
            onChange={(e) => set("case_type", e.target.value)}
          />
        );
      case "year":
        return (
          <TextField
            key="year"
            label={T.filters.year}
            inputMode="numeric"
            value={form.year ?? ""}
            error={errors.year}
            onChange={(e) => set("year", e.target.value)}
            style={card ? undefined : { maxWidth: 120 }}
          />
        );
      case "case_status":
        return (
          <SelectField
            key="case_status"
            label={T.filters.status}
            placeholder={T.filters.anyStatus}
            options={CASE_STATUSES.map((v) => ({ value: v, label: T.filters.statuses[v] ?? v }))}
            value={form.case_status ?? ""}
            onChange={(e) => set("case_status", e.target.value)}
          />
        );
      case "court_no":
        return (
          <SelectField
            key="court_no"
            label={T.filters.court}
            placeholder={T.filters.anyCourt}
            options={withCurrent(courts, form.court_no)}
            value={form.court_no ?? ""}
            onChange={(e) => set("court_no", e.target.value)}
          />
        );
      case "bench":
        return (
          <Fragment key="bench">
            <TextField
              label={T.filters.bench}
              hint={T.filters.benchHint}
              list={datalistId}
              value={form.bench ?? ""}
              error={errors.bench}
              onChange={(e) => set("bench", e.target.value)}
              style={card ? undefined : { minWidth: 320 }}
            />
            <datalist id={datalistId}>
              {(benches.data?.benches ?? []).map((b) => (
                <option key={b.text} value={b.text} />
              ))}
            </datalist>
          </Fragment>
        );
      case "owner":
      case "scored_for":
      case "other_office":
        return departmentField(f);
      case "next_differs":
        // design next-date-direct, decision 5
        return (
          <CheckField
            key="next_differs"
            inline
            label={T.filters.nextDiffers}
            checked={form.next_differs === "true"}
            onChange={(e) => set("next_differs", e.target.checked ? "true" : "")}
          />
        );
    }
  };

  const rowShared = FIELD_ORDER.filter(inRow);
  const moreSharedFields = FIELD_ORDER.filter(inMore);

  if (card) {
    // design portal-ui-polish-2, decision 22: the same fields in the kit's Filter Card
    const heroShared = FIELD_ORDER.find((f) => f === hero && fields.has(f) && !hidden.has(f));
    const heroOwn = own.find((c) => c.key === hero);
    const notHero = (f: SharedField) => f !== hero;
    const notHeroOwn = (c: OwnControl) => c.key !== hero;
    return (
      <FilterCard
        label={T.filters.form}
        hero={heroShared ? sharedField(heroShared) : heroOwn ? ownControl(heroOwn) : null}
        onSubmit={apply}
        more={
          hasMore ? (
            <>
              {moreSharedFields.filter(notHero).map(sharedField)}
              {own.filter((c) => c.more && notHeroOwn(c)).map(ownControl)}
            </>
          ) : null
        }
        moreCount={moreCount}
        moreOpen={open}
        onMoreToggle={onToggle}
        summary={summary}
      >
        {rowShared.filter((f) => f === "q" && notHero(f)).map(sharedField)}
        {own.filter((c) => !c.more && c.first && notHeroOwn(c)).map(ownControl)}
        {rowShared.filter((f) => f !== "q" && notHero(f)).map(sharedField)}
        {own.filter((c) => !c.more && !c.first && notHeroOwn(c)).map(ownControl)}
      </FilterCard>
    );
  }

  return (
    <form
      role="search"
      aria-label={T.filters.form}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
      <div className="stack">
        <div className={s.row}>
          {rowShared.filter((f) => f === "q").map(sharedField)}
          {own.filter((c) => !c.more && c.first).map(ownControl)}
          {rowShared.filter((f) => f !== "q").map(sharedField)}
          {own.filter((c) => !c.more && !c.first).map(ownControl)}
        </div>
        {open && hasMore ? (
          <div className={s.more} id={moreId}>
            {moreSharedFields.map(sharedField)}
            {own.filter((c) => c.more).map(ownControl)}
          </div>
        ) : null}
        <div className={s.actions}>
          <Button type="submit">{T.filters.apply}</Button>
          {hasMore ? (
            <Button variant="secondary" aria-expanded={open} aria-controls={open ? moreId : undefined} onClick={onToggle}>
              {T.filters.more}
            </Button>
          ) : null}
        </div>
      </div>
    </form>
  );
}
