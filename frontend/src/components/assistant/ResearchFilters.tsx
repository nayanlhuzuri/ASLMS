"use client";

/**
 * The Search Filters of My Cases and All Court Orders (design research-index-portal, decisions 6 to 10): one row above
 * the question box with the secondary "Search Filters (n)" (`aria-expanded`) and the line "Filters apply to each
 * question you ask on this tab."; the panel under it in Filter Layout B's field grid (a size container, labels above
 * the boxes, one column on phones), opening in 220 ms (at once under reduced motion), its fields mounted on first
 * opening and kept, out of the tab order while closed; the applied filters as the kit's chips with Clear All, open or
 * closed. There is no Search button: Ask sends the question with the filters in view.
 *
 * The act and the cited judgment pick from `GET /assistant/filter-choices` through `ChoiceField`, the ARIA 1.2
 * combobox of the kit's User Picker: suggestions after 2 characters and a 250 ms pause, arrow keys, Enter picks,
 * Escape closes, each option "label · n orders" with its detail muted, the error state with Try Again (Enter retries
 * only while Try Again is shown). A typed act that was not picked is sent as row 250's key of the words.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { DateRangeField, type DateValue } from "@/components/filters/DateRangeField";
import { FilterChips } from "@/components/filters/FilterChips";
import { Button, CheckField, cx, PickerRetry, retryable } from "@/components/ui";
import c from "@/components/ui/controls.module.css";
import p from "@/components/ui/officePicker.module.css";
import { api, ApiError } from "@/lib/api/client";
import type { AssistantFilterChoices } from "@/lib/api/types";
import { T } from "@/lib/messages";
import {
  actKey,
  actWords,
  CITE_MAX,
  filterChips,
  filtersCount,
  FORMS,
  OUTCOMES,
  removeChip,
  type DateMode,
  type FilterErrors,
  type ResearchFilters as Filters,
} from "@/lib/research";

import s from "./assistant.module.css";

const F = T.assistant.filters;
export const CHOICES_DEBOUNCE_MS = 250;
export const CHOICES_LIMIT = 20;

type Choice = AssistantFilterChoices["items"][number];

function useDebounced<V>(value: V, ms: number): V {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/**
 * One choice field (decision 10): the words typed, and the server's list after 2 characters and a pause. `onText` is
 * every keystroke; `onPick` a choice from the list.
 */
export function ChoiceField({
  kind,
  label,
  hint,
  error,
  text,
  onText,
  onPick,
  maxLength,
}: {
  kind: "act" | "cites";
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  text: string;
  onText: (text: string) => void;
  onPick: (choice: Choice) => void;
  maxLength?: number;
}) {
  const auto = useId();
  const inputId = `${auto}-choice`;
  const listId = `${auto}-list`;
  const hintId = `${auto}-hint`;
  const errorId = `${auto}-error`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const typed = text.trim();
  const settled = useDebounced(typed, CHOICES_DEBOUNCE_MS);
  const enough = settled.length >= 2;
  const choices = useQuery({
    queryKey: ["assistant", "filter-choices", kind, settled],
    queryFn: () => api<AssistantFilterChoices>("/assistant/filter-choices", { query: { kind, q: settled, limit: CHOICES_LIMIT } }),
    enabled: open && enough,
    staleTime: 60_000,
    retry: false,
  });
  const notReady = choices.data?.ready === false;
  const shown = enough && typed.length >= 2 && settled === typed ? (choices.data?.items ?? []) : [];
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [place, setPlace] = useState<CSSProperties>({});
  const [host, setHost] = useState<Element | null>(null);

  function position() {
    const el = box.current;
    if (!el || typeof window === "undefined") return;
    const r = el.getBoundingClientRect();
    const room = window.innerHeight - r.bottom;
    const above = room < 240 && r.top > room;
    const width = Math.min(Math.max(r.width, 300), window.innerWidth - 32);
    setPlace({
      left: Math.max(16, Math.min(r.left, window.innerWidth - 16 - width)),
      width,
      ...(above ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
    });
  }

  useEffect(() => {
    if (!open) return;
    position();
    const onMove = () => position();
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [open]);

  // a new answer makes its first option active (state adjusted while rendering)
  const answerKey = shown.map((o) => o.value).join("\u0001");
  const [seenKey, setSeenKey] = useState(answerKey);
  if (seenKey !== answerKey) {
    setSeenKey(answerKey);
    setActive(0);
  }

  useEffect(() => {
    if (!open || !list.current) return;
    list.current.querySelector<HTMLElement>(`[data-index='${active}']`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  function openList() {
    setHost(box.current?.closest("[role='dialog']") ?? document.body);
    setOpen(true);
  }

  function choose(i: number) {
    const o = shown[i];
    if (!o) return;
    onPick(o);
    setOpen(false);
    input.current?.focus();
  }

  const failed = choices.isError && !choices.isFetching;
  let note: string | null = null;
  let errorNote: string | null = null;
  if (typed.length < 2) note = F.minimum;
  else if (!enough || settled !== typed || choices.isPending || (choices.isError && choices.isFetching)) note = F.loading;
  else if (failed) {
    errorNote = F.failed;
    note = errorNote;
  } else if (notReady) note = F.notReady;
  else if (shown.length === 0) note = F.none(typed);
  // row 186: Try Again and Enter share this one condition
  const retryShown = errorNote !== null && retryable(choices.error);

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList();
        else setActive((a) => Math.min(a + 1, Math.max(0, shown.length - 1)));
        return;
      case "ArrowUp":
        e.preventDefault();
        if (open) setActive((a) => Math.max(0, a - 1));
        return;
      case "Enter":
        if (!open) return;
        e.preventDefault();
        if (retryShown) void choices.refetch();
        else choose(active);
        return;
      case "Escape":
        if (!open) return;
        e.preventDefault();
        e.stopPropagation();
        setOpen(false);
        return;
      case "Tab":
        if (open) setOpen(false);
        return;
    }
  }

  const activeId = open && !note && shown[active] ? `${listId}-${active}` : undefined;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  const popover = open ? (
    <div className={cx(p.pop, host === document.body && p.popTop)} style={place} data-ui="choice-list">
      <ul ref={list} id={listId} role="listbox" aria-label={F.listAria} className={p.list}>
        {note ? (
          <li className={p.none} role="presentation">
            {note}
          </li>
        ) : (
          shown.map((o, i) => {
            const orders = F.optionOrders(o.orders);
            return (
              <li
                key={o.value}
                id={`${listId}-${i}`}
                data-index={i}
                role="option"
                aria-selected={i === active}
                aria-label={[`${o.label} · ${orders}`, o.detail].filter(Boolean).join(", ")}
                className={cx(p.option, s.choiceOption, i === active && p.active)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(i);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span className={s.choiceLabel}>
                  {o.label} · {orders}
                </span>
                {o.detail ? <span className={s.choiceDetail}>{o.detail}</span> : null}
              </li>
            );
          })
        )}
      </ul>
      {retryShown ? <PickerRetry onRetry={() => void choices.refetch()} /> : null}
    </div>
  ) : null;

  return (
    <div className={cx(c.field, s.choiceField)} data-ui="choice-field">
      <label className={c.label} htmlFor={inputId}>
        {label}
      </label>
      <div ref={box} className={p.box}>
        <input
          ref={input}
          id={inputId}
          className={cx(c.input, c.control, s.choiceInput)}
          data-ui="field"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          autoComplete="off"
          maxLength={maxLength}
          value={text}
          onChange={(e) => {
            onText(e.target.value);
            if (!open) openList();
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={onKey}
        />
      </div>
      {hint ? (
        <span id={hintId} className={c.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className={c.error} role="alert">
          {error}
        </span>
      ) : null}
      <span className="visually-hidden" role="status">
        {open ? (errorNote ?? (notReady ? F.notReady : "")) : ""}
      </span>
      {popover && host ? createPortal(popover, host) : null}
    </div>
  );
}

function CheckGroup({
  legend,
  values,
  labels,
  chosen,
  onChange,
  hint,
}: {
  legend: string;
  values: readonly string[];
  labels: Record<string, string>;
  chosen: string[];
  onChange: (next: string[]) => void;
  hint?: string;
}) {
  const hintId = useId();
  return (
    <fieldset className={s.checkGroup} aria-describedby={hint ? hintId : undefined}>
      <legend className={c.label}>{legend}</legend>
      {values.map((v) => (
        <CheckField
          key={v}
          label={labels[v]}
          checked={chosen.includes(v)}
          onChange={(e) => onChange(e.target.checked ? values.filter((x) => x === v || chosen.includes(x)) : chosen.filter((x) => x !== v))}
        />
      ))}
      {hint ? (
        <span id={hintId} className={c.hint}>
          {hint}
        </span>
      ) : null}
    </fieldset>
  );
}

const DATE_PRESETS = [
  { value: "", label: F.dateAny },
  { value: "date", label: F.dateOne },
  { value: "range", label: F.dateRange },
];

/** The panel row, the panel and the applied chips (decisions 6 and 7). */
export function ResearchFilters({
  filters,
  onChange,
  errors,
  actLabels,
  onActLabel,
  actError,
}: {
  filters: Filters;
  onChange: (next: Filters) => void;
  errors: FilterErrors;
  /** the labels of acts picked from the list, by key (the chips show them) */
  actLabels: ReadonlyMap<string, string>;
  onActLabel: (key: string, label: string) => void;
  /** the server answered `bad_filter`: the act field says so */
  actError?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  if (open && !opened) setOpened(true);
  const panelId = useId();
  const count = filtersCount(filters);
  // the act field's words: the label as picked, or what was typed; reset when the key changes from outside (a chip)
  const [actText, setActText] = useState(() => (filters.act ? actWords(filters.act, actLabels) : ""));
  const shownKey = actLabels.has(filters.act) && actLabels.get(filters.act) === actText ? filters.act : actKey(actText);
  if (shownKey !== filters.act.trim()) {
    const next = filters.act ? actWords(filters.act, actLabels) : "";
    if (next !== actText) setActText(next);
  }
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const chips = filterChips(filters, actLabels);
  const date: DateValue = { mode: filters.dateMode, from: filters.from, to: filters.to };
  return (
    <div className={s.filters} data-ui="research-filters">
      <div className={s.filtersRow}>
        <Button variant="secondary" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
          {F.button(count)}
        </Button>
        <span className={s.hint}>{F.line}</span>
      </div>
      <div
        id={panelId}
        className={cx(s.filtersPanel, open && s.filtersPanelOpen)}
        role="group"
        aria-label={F.panel}
        inert={!open}
        aria-hidden={!open}
        data-ui="research-filters-panel"
      >
        <div className={s.filtersInner}>
          {opened ? (
            <div className={s.filtersGrid}>
              <CheckGroup legend={F.formLabel} values={FORMS} labels={F.forms} chosen={filters.forms} onChange={(forms) => set({ forms })} />
              <CheckField
                inline
                label={F.substantive}
                hint={F.substantiveHint}
                checked={filters.substantive}
                onChange={(e) => set({ substantive: e.target.checked })}
              />
              <CheckGroup
                legend={F.outcomeLabel}
                values={OUTCOMES}
                labels={F.outcomes}
                chosen={filters.outcomes}
                onChange={(outcomes) => set({ outcomes })}
                hint={F.outcomeHint}
              />
              <CheckField
                inline
                label={F.againstState}
                hint={F.againstStateHint}
                checked={filters.againstState}
                onChange={(e) => set({ againstState: e.target.checked })}
              />
              <ChoiceField
                kind="cites"
                label={F.cites}
                hint={F.citesHint}
                error={errors.cites}
                text={filters.cites}
                onText={(cites) => set({ cites })}
                onPick={(o) => set({ cites: o.value })}
                maxLength={200}
              />
              <ChoiceField
                kind="act"
                label={F.act}
                hint={F.actHint}
                error={actError ?? undefined}
                text={actText}
                onText={(t) => {
                  setActText(t);
                  set({ act: actKey(t) });
                }}
                onPick={(o) => {
                  onActLabel(o.value, o.label);
                  setActText(o.label);
                  set({ act: o.value });
                }}
                maxLength={200}
              />
              <DateRangeField
                label={F.orderDate}
                presets={DATE_PRESETS}
                value={date}
                errors={{ to: errors.to, from: errors.from }}
                onChange={(d) => {
                  const mode = (d.mode === "date" || d.mode === "range" ? d.mode : "") as DateMode;
                  set({ dateMode: mode, from: mode ? d.from : "", to: mode ? d.to : "" });
                }}
              />
            </div>
          ) : null}
        </div>
      </div>
      <FilterChips
        chips={chips}
        onRemove={(keys) => onChange(removeChip(filters, keys))}
        onClearAll={() => onChange({ ...filters, forms: [], substantive: false, outcomes: [], againstState: false, cites: "", act: "", dateMode: "", from: "", to: "" })}
      />
    </div>
  );
}

/** A citation over the limit, in the field's own words (shared with the tests). */
export const CITES_LIMIT = CITE_MAX;

/** Whether an answer error is the server's `bad_filter`. */
export function isBadFilter(error: unknown): boolean {
  return error instanceof ApiError && error.code === "bad_filter";
}
