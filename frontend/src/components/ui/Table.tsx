import type { ReactNode } from "react";
import s from "./ui.module.css";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Label used on phones, where rows become stacked cards. Defaults to the header when it is a string. */
  label?: string;
  render: (row: T) => ReactNode;
  mono?: boolean;
  num?: boolean;
  actions?: boolean;
  width?: string | number;
}

/** A table that becomes stacked cards on narrow screens. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  bare,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string;
  caption?: string;
  bare?: boolean;
}) {
  return (
    <div className={bare ? s.tableWrapBare : s.tableWrap}>
      <table className={`${s.table} ${s.stack}`}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.num ? s.num : undefined} style={c.width ? { width: c.width } : undefined}>
                {c.actions && !c.header ? <span className="sr-only">Actions</span> : c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  data-label={c.actions ? "" : (c.label ?? (typeof c.header === "string" ? c.header : ""))}
                  className={[c.num ? s.num : "", c.actions ? s.actions : "", c.mono ? "mono" : ""].join(" ")}
                >
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
