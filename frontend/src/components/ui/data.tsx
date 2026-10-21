"use client";

/**
 * Data display of the UI kit (design portal-ui-redesign, decisions 15, 17 and 18): the responsive `DataTable` (a real
 * table on wide screens, the same rows as cards on phones; the plain `Table` left the kit in design portal-ui-polish,
 * decision 15, so no list scrolls sideways), pagination, definition lists, case links and the alignment rule's fixed
 * leading columns (`Lead`, `DateChip`, `LeadIcon`) composed by `ListRow`.
 */
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { dayMonth, formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

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

/** `fitTable` after every render (rows or columns may have changed) and whenever the box's width changes. */
function useFitTable() {
  const node = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  useLayoutEffect(() => fitTable(node.current));
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
    });
    observer.current.observe(el);
    void document.fonts?.ready.then(() => fitTable(node.current));
  }, []);
  return ref;
}

/**
 * One DOM for every width (decision 18): a `<table>` on wide screens; below 820 px CSS turns each row into a card
 * with its primary cell on top and the other cells as label-value lines from each cell's `data-label`. A row with
 * `onRowClick` opens by click or by Enter on the focused row. On a wider screen a table whose columns cannot fit its
 * box becomes the same cards (`fitTable`), so no column is ever cut off or scrolled to.
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
}) {
  const wrapRef = useFitTable();
  if (rows.length === 0 && empty) return <>{empty}</>;
  return (
    <div className={s.dataWrap} ref={wrapRef}>
      <table className={cx(s.table, s.dataTable)}>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cx(c.align === "right" && s.num, c.hideOnPhone && s.hideOnPhone)}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.header}
              </th>
            ))}
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
export function CopyButton({ text, label = T.copy }: { text: string; label?: string }) {
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
      <Button variant="ghost" size="sm" onClick={() => void copy()}>
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
 * `label` names the block for screen readers.
 */
export function CodeBlock({ children, label, copy = true }: { children: string; label: string; copy?: boolean }) {
  return (
    <figure className={s.codeBlock} data-ui="code">
      <figcaption className={s.codeHead}>
        <span className={s.codeLabel}>{label}</span>
        {copy ? <CopyButton text={children} /> : null}
      </figcaption>
      <pre className={s.code} tabIndex={0} aria-label={label}>
        <code>{children}</code>
      </pre>
    </figure>
  );
}
