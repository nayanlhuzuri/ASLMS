"use client";

/**
 * The kit's list search and sort controls (design list-search, decisions 2, 7, 8, 33 and 35):
 *
 * - `ListToolbar`: a list's one toolbar line: the search, the sort, the list's own controls, then the order line and
 *   the count pushed right; it wraps on the control line and stacks on phones.
 * - `ListSearch`: a `type="search"` field in a `role="search"` wrapper, the label kept for screen readers and shown as
 *   the placeholder, a "Clear Search" button inside the field, Escape to clear (focus stays in the field), Enter to
 *   send at once, a small spinner while a server search runs.
 * - `ListCount`: "340 codes", "12 of 340 codes" or "12 codes match", announced politely.
 * - `NoMatches`: "No matches for “ram”." with Clear Search, shown instead of the list's own empty state.
 * - `ListSort`: the Sort By select and a direction button named by the current direction; "Default" hides it.
 * - `OrderLine`: "Order: Newest First", or "Sorted by Next Hearing, Earliest First" with Default Order.
 */
import { useId, useRef, type ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { dirWord, firstDirOf, type SortDir, type SortState, type SortType } from "@/lib/sort";

import { Button, cx } from "./controls";
import s from "./listSearch.module.css";

export function ListToolbar({
  search,
  sort,
  count,
  order,
  children,
  label,
}: {
  search?: ReactNode;
  sort?: ReactNode;
  count?: ReactNode;
  /** The order line ("Order: Newest First"), beside the count. */
  order?: ReactNode;
  children?: ReactNode;
  /** A name for the line when it holds no search (the search names itself). */
  label?: string;
}) {
  return (
    <div className={s.toolbar} data-ui="list-toolbar" role={label ? "group" : undefined} aria-label={label}>
      {search ? <div className={s.searchSlot}>{search}</div> : null}
      {sort ? <div className={s.sortSlot}>{sort}</div> : null}
      {children ? <div className={s.controls}>{children}</div> : null}
      {order || count ? (
        <div className={s.trail}>
          {order}
          {count}
        </div>
      ) : null}
    </div>
  );
}

export function ListSearch({
  label,
  placeholder,
  value,
  onChange,
  onEnter,
  minChars,
  busy,
}: {
  label: string;
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
  /** Enter: send a server search at once, without waiting for the pause. */
  onEnter?: () => void;
  /** Shown as a tooltip ("Type at least 2 letters."). */
  minChars?: number;
  busy?: boolean;
}) {
  const id = useId();
  const own = useRef<HTMLInputElement | null>(null);
  function clear() {
    onChange("");
    own.current?.focus();
  }
  return (
    <div role="search" aria-label={label} className={s.search} data-ui="list-search">
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <input
        id={id}
        ref={own}
        type="search"
        className={cx(s.input, value && s.withClear, busy && s.withBusy)}
        placeholder={placeholder ?? label}
        title={minChars ? T.list.minCharsTooltip(minChars) : undefined}
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.preventDefault();
            e.stopPropagation();
            clear();
          } else if (e.key === "Enter") {
            e.preventDefault();
            onEnter?.();
          }
        }}
      />
      {busy ? <span className={s.spinner} aria-hidden="true" data-ui="list-search-busy" /> : null}
      {value ? (
        <button type="button" className={s.clear} aria-label={T.list.clearSearchLabel} title={T.list.clearSearchLabel} onClick={clear}>
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      ) : null}
    </div>
  );
}

/** "340 codes"; searching, "12 of 340 codes" when the total before the search is known, else "12 codes match". */
export function ListCount({
  shown,
  total,
  noun,
  nounOne,
  allNoun,
  allNounOne,
  searching,
}: {
  shown: number | null | undefined;
  /** The count before the search (`total_all`), when known. */
  total?: number | null;
  noun: string;
  /** The noun after "1" ("1 code"); default `noun`. */
  nounOne?: string;
  /** The words after the number when not searching ("codes not mapped"); default `noun`. */
  allNoun?: string;
  allNounOne?: string;
  searching: boolean;
}) {
  if (shown === null || shown === undefined) return null;
  const n = formatNumber(shown);
  const one = (many: string, single: string | undefined, count: number) => (count === 1 && single ? single : many);
  let text: string;
  if (!searching) text = T.list.count(n, allNoun ? one(allNoun, allNounOne, shown) : one(noun, nounOne, shown));
  else if (typeof total === "number") text = T.list.countOf(n, formatNumber(total), one(noun, nounOne, total));
  else text = T.list.countMatch(n, one(noun, nounOne, shown));
  return (
    <span className={s.count} aria-live="polite" data-ui="list-count">
      {text}
    </span>
  );
}

/** Instead of the list's own empty state while a search is set and nothing matches. */
export function NoMatches({ q, onClear, children }: { q: string; onClear: () => void; children?: ReactNode }) {
  return (
    <div className={s.noMatches} data-ui="no-matches">
      <p>{children ?? T.list.noMatches(q.trim())}</p>
      <Button variant="secondary" onClick={onClear}>
        {T.list.clearSearchLabel}
      </Button>
    </div>
  );
}

export interface SortOption {
  key: string;
  label: string;
  type: SortType;
  firstDir?: SortDir;
  labels?: readonly [string, string];
}

/** The words of a sort ("Next Hearing, Earliest First"). */
export function sortWords(option: SortOption, dir: SortDir): string {
  return dirWord(option.type, dir, option.firstDir, option.labels);
}

/** Decision 33: the Sort By select (Default, then each sortable column) and the direction button. */
export function ListSort({
  options,
  sort,
  onSort,
  defaultLabel,
}: {
  options: SortOption[];
  sort: SortState | null;
  onSort: (next: SortState | null) => void;
  /** The list's default order's name ("Newest First"). */
  defaultLabel: string;
}) {
  const id = useId();
  const current = sort ? options.find((o) => o.key === sort.key) : undefined;
  return (
    <div className={s.sort} data-ui="list-sort">
      <label htmlFor={id} className={s.sortLabel}>
        {T.list.sortByLabel}
      </label>
      <select
        id={id}
        className={s.select}
        value={current ? current.key : ""}
        onChange={(e) => {
          const option = options.find((o) => o.key === e.target.value);
          onSort(option ? { key: option.key, dir: firstDirOf(option.type, option.firstDir) } : null);
        }}
      >
        <option value="">{T.list.defaultOption(defaultLabel)}</option>
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
      {current && sort ? (
        <Button
          variant="secondary"
          className={s.dirButton}
          aria-label={sortWords(current, sort.dir)}
          title={sortWords(current, sort.dir)}
          onClick={() => onSort({ key: sort.key, dir: sort.dir === "asc" ? "desc" : "asc" })}
        >
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            {sort.dir === "asc" ? <path d="M8 13V3M4 7l4-4 4 4" /> : <path d="M8 3v10M4 9l4 4 4-4" />}
          </svg>
          <span className={s.dirText}>{sortWords(current, sort.dir)}</span>
        </Button>
      ) : null}
    </div>
  );
}

/** Decision 35: the list's order in words, with Default Order once a sort is chosen. */
export function OrderLine({
  options,
  sort,
  defaultLabel,
  onReset,
}: {
  options: SortOption[];
  sort: SortState | null;
  defaultLabel: string;
  onReset: () => void;
}) {
  const current = sort ? options.find((o) => o.key === sort.key) : undefined;
  if (!current || !sort) {
    return (
      <span className={s.order} data-ui="order-line">
        {T.list.orderLine(defaultLabel)}
      </span>
    );
  }
  return (
    <span className={s.order} data-ui="order-line">
      {T.list.sortedBy(current.label, sortWords(current, sort.dir))}
      <Button variant="link" className={s.resetButton} onClick={onReset}>
        {T.list.defaultOrderButton}
      </Button>
    </span>
  );
}
