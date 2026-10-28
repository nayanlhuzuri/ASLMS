"use client";

/**
 * Data display of the UI kit (design portal-ui-redesign, decisions 15, 17 and 18): the responsive `DataTable` (a real
 * table on wide screens, the same rows as cards on phones; the plain `Table` left the kit in design portal-ui-polish,
 * decision 15, so no list scrolls sideways), pagination, definition lists, case links and the alignment rule's fixed
 * leading columns (`Lead`, `DateChip`, `LeadIcon`) composed by `ListRow`.
 */
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { dayMonth, formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { dirWord, firstDirOf, nextSort, sortRows, type Sortable, type SortDir, type SortState, type SortType } from "@/lib/sort";

import { Button, cx } from "./controls";
import s from "./data.module.css";

/** The right-aligned tabular-figures cell class, for `ReportView`'s own scrollable table. */
export const numCell = s.num!;

export interface Column<Row> {
  key: string;
  header: ReactNode;
  /** The label on the phone card (default: the header when it is text). */
  label?: string;
  cell: (row: Row) => ReactNode;
  /** A fixed width (status columns), for example `var(--lead-w)` or `120px`. */
  width?: string;
  align?: "left" | "right";
  /** Left out of the phone cards. */
  hideOnPhone?: boolean;
  /** The cell on top of the phone card, without a label. */
  primary?: boolean;
  /** Drawn as the row's header (`<th scope="row">`), for a primary cell that names the row. */
  rowHeader?: boolean;
  /**
   * A sortable column (design list-search, decision 27): its header becomes a button. `key` defaults to the column's
   * key; `value` is what a list sorted in the browser compares; `labels` names the two directions (`[asc, desc]`).
   */
  sort?: ColumnSort<Row>;
}

export interface ColumnSort<Row> {
  key?: string;
  type: SortType;
  firstDir?: SortDir;
  value?: (row: Row) => Sortable;
  labels?: readonly [string, string];
}

/** The sort key of a sortable column. */
export function sortKeyOf<Row>(c: Column<Row>): string {
  return c.sort?.key ?? c.key;
}

export interface ColumnSortOption {
  key: string;
  label: string;
  type: SortType;
  firstDir?: SortDir;
  labels?: readonly [string, string];
}

/** The kit `ListSort` options of a table's sortable columns, in column order. */
export function sortOptionsOf<Row>(columns: Column<Row>[]): ColumnSortOption[] {
  return columns
    .filter((c) => c.sort)
    .map((c) => ({
      key: sortKeyOf(c),
      label: c.label ?? (typeof c.header === "string" ? c.header : sortKeyOf(c)),
      type: c.sort!.type,
      firstDir: c.sort!.firstDir,
      labels: c.sort!.labels,
    }));
}

/**
 * A list held whole in the browser, ordered by the sorted column's `value` (stable, blanks last in both directions);
 * the rows as given when no sort is set or the column is unknown.
 */
export function sortByColumn<Row>(rows: Row[], columns: Column<Row>[], sort: SortState | null | undefined): Row[] {
  if (!sort) return rows;
  const column = columns.find((c) => c.sort && sortKeyOf(c) === sort.key);
  if (!column?.sort?.value) return rows;
  return sortRows(rows, column.sort.value, column.sort.type, sort.dir);
}

/**
 * A sortable column head (decision 27), also for hand-written tables: a `<th>` with `aria-sort` only while it is the
 * sorted column (or the default column in the default order), holding a button with the header's text. Clicks cycle
 * the column's first direction, the other, then the list's default; focus stays on the button.
 */
export function SortHeader({
  children,
  sortKey,
  type,
  firstDir,
  labels,
  sort,
  defaultSort,
  onSort,
  onAnnounce,
  label,
  className,
  style,
}: {
  children: ReactNode;
  sortKey: string;
  type: SortType;
  firstDir?: SortDir;
  labels?: readonly [string, string];
  sort: SortState | null | undefined;
  defaultSort?: SortState | null;
  onSort: (next: SortState | null) => void;
  onAnnounce?: (text: string) => void;
  /** The column's name in the announcement (default: the header when it is text). */
  label?: string;
  className?: string;
  style?: CSSProperties;
}) {
  const active = sort ? (sort.key === sortKey ? sort : null) : defaultSort?.key === sortKey ? defaultSort : null;
  const ariaSort = active ? (active.dir === "asc" ? "ascending" : "descending") : undefined;
  const first = firstDirOf(type, firstDir);
  const name = label ?? (typeof children === "string" ? children : sortKey);
  return (
    <th scope="col" aria-sort={ariaSort} className={className} style={style} data-sortable="">
      <button
        type="button"
        className={s.sortButton}
        data-sorted={active ? active.dir : undefined}
        onClick={() => {
          const next = nextSort(sort ?? null, sortKey, first);
          onSort(next);
          onAnnounce?.(next ? T.list.sortedBy(name, dirWord(type, next.dir, firstDir, labels)) : T.list.sortedDefaultNote);
        }}
      >
        <span>{children}</span>
        <svg className={s.sortIcon} aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          {active ? active.dir === "asc" ? <path d="M6 10V2M3 5l3-3 3 3" /> : <path d="M6 2v8M3 7l3 3 3-3" /> : <path d="M4 4.5 6 2.5l2 2M4 7.5l2 2 2-2" />}
        </svg>
      </button>
    </th>
  );
}

/**
 * Draws the table as cards (`data-stacked`) when, as a table, it is wider than its box: decided in table form each
 * time, before paint, so a narrower box or more columns turn it into cards and a wider box back into a table. Below
 * 820 px the CSS already draws cards and a table never measures wider than its box.
 */
export function fitTable(wrap: HTMLElement | null): void {
  const table = wrap?.querySelector("table");
  if (!wrap || !table) return;
  wrap.removeAttribute("data-stacked");
  if (table.offsetWidth > wrap.clientWidth + 1) wrap.setAttribute("data-stacked", "");
}

/**
 * `fitTable` when the data changes (the `rows` array, stable under React Query's structural sharing while the data is
 * unchanged, or the column keys), not on every render (design followups-oct, decision 23), and whenever the box's
 * width changes. Comparing only counts was rejected: a refetch with the same counts and longer text must re-measure.
 */
function useFitTable(rows: unknown, columnKeys: string, onStacked?: (stacked: boolean) => void) {
  const node = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const report = useRef(onStacked);
  const last = useRef<boolean | null>(null);
  useLayoutEffect(() => {
    report.current = onStacked;
  });
  // design list-search, decision 33: the list's toolbar shows the Sort By select whenever the table is drawn as cards
  const tell = useCallback(() => {
    const el = node.current;
    if (!el || !report.current) return;
    const narrow =
      typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 819px)").matches;
    const stacked = narrow || el.hasAttribute("data-stacked");
    if (stacked !== last.current) {
      last.current = stacked;
      report.current(stacked);
    }
  }, []);
  useLayoutEffect(() => {
    fitTable(node.current);
    tell();
  }, [rows, columnKeys, tell]);
  const ref = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    node.current = el;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = -1;
    observer.current = new ResizeObserver(() => {
      if (el.clientWidth === width) return; // a height change (cards ↔ table) is not a reason to measure again
      width = el.clientWidth;
      fitTable(el);
      tell();
    });
    observer.current.observe(el);
    void document.fonts?.ready.then(() => {
      fitTable(node.current);
      tell();
    });
  }, [tell]);
  return ref;
}

/**
 * One DOM for every width (decision 18): a `<table>` on wide screens; below 820 px CSS turns each row into a card
 * with its primary cell on top and the other cells as label-value lines from each cell's `data-label`. A row with
 * `onRowClick` opens by click or by Enter on the focused row. On a wider screen a table whose columns cannot fit its
 * box becomes the same cards (`fitTable`), so no column is ever cut off or scrolled to. The caption is hidden unless
 * `showCaption` (design data-collection-redesign, decision 10).
 */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  caption,
  onRowClick,
  rowLabel,
  rowClassName,
  empty,
  showCaption = false,
  sort,
  onSort,
  defaultSort,
  onStackedChange,
}: {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  caption?: ReactNode;
  onRowClick?: (row: Row) => void;
  /** The accessible name of a clickable row. */
  rowLabel?: (row: Row) => string;
  /** An extra class for a row (a changed value on the audit entry). */
  rowClassName?: (row: Row) => string | undefined;
  /** Shown instead of the table when there are no rows. */
  empty?: ReactNode;
  /**
   * Shows the caption (design data-collection-redesign, decision 10): by default it stays in the markup, visually
   * hidden, as the table's accessible name, because the panel's heading above already says it. A table with no
   * visible heading of its own shows it.
   */
  showCaption?: boolean;
  /** The chosen sort (design list-search, decision 27); null or left out is the list's default order. */
  sort?: SortState | null;
  /** Set with the sortable columns: a header press gives the next sort (null: back to the default). */
  onSort?: (next: SortState | null) => void;
  /** The default order when it is one of the columns (its header then carries `aria-sort`). */
  defaultSort?: SortState | null;
  /** Whether the table is drawn as cards (below 820 px, or `data-stacked`): the toolbar's Sort By select shows. */
  onStackedChange?: (stacked: boolean) => void;
}) {
  const wrapRef = useFitTable(rows, columns.map((c) => c.key).join("\u0000"), onStackedChange);
  const [said, setSaid] = useState("");
  if (rows.length === 0 && empty) return <>{empty}</>;
  return (
    <div className={s.dataWrap} ref={wrapRef}>
      <table className={cx(s.table, s.dataTable)}>
        {caption ? <caption className={showCaption ? undefined : s.srCaption}>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => {
              const className = cx(c.align === "right" && s.num, c.hideOnPhone && s.hideOnPhone);
              const style = c.width ? { width: c.width } : undefined;
              if (c.sort && onSort) {
                return (
                  <SortHeader
                    key={c.key}
                    sortKey={sortKeyOf(c)}
                    type={c.sort.type}
                    firstDir={c.sort.firstDir}
                    labels={c.sort.labels}
                    sort={sort}
                    defaultSort={defaultSort}
                    onSort={onSort}
                    onAnnounce={setSaid}
                    label={c.label}
                    className={className}
                    style={style}
                  >
                    {c.header}
                  </SortHeader>
                );
              }
              return (
                <th key={c.key} scope="col" className={className} style={style}>
                  {c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const open = onRowClick ? () => onRowClick(row) : undefined;
            return (
              <tr
                key={rowKey(row)}
                className={cx(open && s.clickable, rowClassName?.(row))}
                tabIndex={open ? 0 : undefined}
                aria-label={open && rowLabel ? rowLabel(row) : undefined}
                onClick={
                  open
                    ? (e) => {
                        // a link or a control inside the row does its own job, not the row's
                        const inner = (e.target as HTMLElement).closest?.("a, button, input, select, textarea, label");
                        if (inner && e.currentTarget.contains(inner)) return;
                        open();
                      }
                    : undefined
                }
                onKeyDown={
                  open
                    ? (e: KeyboardEvent<HTMLTableRowElement>) => {
                        if (e.key === "Enter" && e.target === e.currentTarget) {
                          e.preventDefault();
                          open();
                        }
                      }
                    : undefined
                }
              >
                {columns.map((c) => {
                  const label = c.label ?? (typeof c.header === "string" ? c.header : undefined);
                  const Cell = c.rowHeader ? "th" : "td";
                  return (
                    <Cell
                      key={c.key}
                      scope={c.rowHeader ? "row" : undefined}
                      className={cx(c.align === "right" && s.num, c.hideOnPhone && s.hideOnPhone, c.primary && s.primaryCell)}
                      data-label={c.hideOnPhone || c.primary ? undefined : label}
                    >
                      {/* one box per cell, so a cell of several lines stays one value on the phone card */}
                      <div className={s.cellValue}>{c.cell(row)}</div>
                    </Cell>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {onSort ? (
        <span className="visually-hidden" role="status" aria-live="polite">
          {said}
        </span>
      ) : null}
    </div>
  );
}

export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const to = Math.min(offset + limit, total);
  return (
    <div className={s.pagination}>
      <span className="muted">{T.pageOf(offset + 1, to, formatNumber(total))}</span>
      <Button variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        {T.previous}
      </Button>
      <Button variant="secondary" disabled={to >= total} onClick={() => onChange(offset + limit)}>
        {T.next}
      </Button>
    </div>
  );
}

export function DefinitionList({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className={s.dl}>
      {items.map(([label, value], i) => (
        <div key={i} className={s.contents}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === "" ? "—" : value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Two-column facts (label 140 px, value), as in the side panel. */
export function KvList({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className={s.kv}>
      {items.map(([label, value], i) => (
        <div key={i} className={s.contents}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === "" ? "—" : value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface CaseRefLike {
  ref_no: string;
  cnr?: string | null;
  case_no_text?: string | null;
}

/**
 * A case reference (case number, else `ref_no`; the CNR as its title) as a link to the case page. A case number is
 * semibold with tabular figures; a bare `ref_no` stays monospace (decision 10.1). A case the caller cannot open
 * (`visible: false`) is plain text, never a link, because opening it answers 404.
 */
export function CaseLink({
  value,
  visible = true,
  newTab = false,
}: {
  value: CaseRefLike | null | undefined;
  visible?: boolean;
  /** Opens the case page in a new tab (the claim modal's Linked cases, design portal-ui-redesign, decision 7). */
  newTab?: boolean;
}) {
  if (!value) return <span>—</span>;
  const text = value.case_no_text || value.ref_no;
  const className = value.case_no_text ? "cno" : "mono";
  if (!visible) {
    return (
      <span className={className} title={value.cnr ?? undefined}>
        {text}
      </span>
    );
  }
  return (
    <Link
      href={casePath(value.ref_no)}
      className={className}
      title={value.cnr ?? undefined}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noopener noreferrer" : undefined}
    >
      {text}
    </Link>
  );
}

/** The fixed 96 px leading column for a status badge (the alignment rule, decision 15). */
export function Lead({ children }: { children: ReactNode }) {
  return (
    <span className={s.lead} data-lead="lead">
      {children}
    </span>
  );
}

/** The fixed 48 px leading column with the day over the month of a date (IST), or a dash without one; `hot` is red. */
export function DateChip({ date, hot }: { date: string | null | undefined; hot?: boolean }) {
  const parts = dayMonth(date);
  return (
    <span className={cx(s.dateChip, hot && s.hot)} data-lead="date">
      {date && parts ? (
        <time dateTime={date} title={formatDate(date)}>
          <b>{parts.day}</b>
          <span>{parts.month}</span>
        </time>
      ) : (
        <b aria-hidden="true">—</b>
      )}
    </span>
  );
}

/** The fixed 20 px leading column for an icon. */
export function LeadIcon({ children }: { children: ReactNode }) {
  return (
    <span className={s.leadIcon} data-lead="icon" aria-hidden="true">
      {children}
    </span>
  );
}

/** A row with a fixed leading element (`Lead`, `DateChip` or `LeadIcon`), the body and an optional trailing slot. */
export function ListRow({
  lead,
  children,
  trail,
  as = "div",
}: {
  lead?: ReactNode;
  children: ReactNode;
  trail?: ReactNode;
  as?: "div" | "li";
}) {
  const Tag = as;
  return (
    <Tag className={s.listRow}>
      {lead}
      <div className={s.listBody}>{children}</div>
      {trail ? <div className={s.listTrail}>{trail}</div> : null}
    </Tag>
  );
}

/**
 * A copy button (design system-health-inspector, decision 14): copies `text` and announces "Copied" to screen readers
 * through a polite live region; a refused clipboard announces that instead.
 */
/** `size` defaults to `sm`; a toolbar outside a row uses `md` (36 px) so it is never a small button (followups-oct, 14). */
export function CopyButton({ text, label = T.copy, size = "sm" }: { text: string; label?: string; size?: "sm" | "md" }) {
  const [said, setSaid] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setSaid(T.copied);
    } catch {
      setSaid(T.copyFailed);
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setSaid(""), 2000);
  }
  return (
    <span className={s.copyWrap}>
      <Button variant="ghost" size={size} onClick={() => void copy()}>
        {label}
      </Button>
      <span className={s.copyStatus} role="status" aria-live="polite">
        {said}
      </span>
    </span>
  );
}

/**
 * Monospace text in a block that scrolls sideways inside itself, never the page (decision 14), with a copy button.
 * `label` names the block for screen readers. The block carries `data-scroll-x`, the third place the browser check
 * (`frontend/e2e`, design portal-ui-polish, decision 21) allows to scroll sideways, after `Tabs` and `ReportView`:
 * sideways scrolling is right for code, which is never wrapped (owner, 28 Oct 2026).
 */
export function CodeBlock({
  children,
  label,
  copy = true,
  copySize = "sm",
}: {
  children: string;
  label: string;
  copy?: boolean;
  copySize?: "sm" | "md";
}) {
  return (
    <figure className={s.codeBlock} data-ui="code">
      <figcaption className={s.codeHead}>
        <span className={s.codeLabel}>{label}</span>
        {copy ? <CopyButton text={children} size={copySize} /> : null}
      </figcaption>
      <pre className={s.code} tabIndex={0} aria-label={label} data-scroll-x="">
        <code>{children}</code>
      </pre>
    </figure>
  );
}
