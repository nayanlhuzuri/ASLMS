"use client";

/**
 * A date filter (design portal-filters, decision 10): a preset select (Any, the list's presets, "A date", "Between
 * dates") and, for the last two, one or two date inputs. Dates are IST calendar days (`YYYY-MM-DD`).
 */
import { SelectField, TextField } from "@/components/ui";
import type { DateMode } from "@/lib/filters";
import { T } from "@/lib/messages";

import s from "./filters.module.css";

export interface DateValue {
  mode: DateMode;
  from: string;
  to: string;
}

export function DateRangeField({
  label,
  presets,
  value,
  onChange,
  errors = {},
}: {
  label: string;
  /** The preset choices in order, with their labels (including "" for Any, `date` and `range`). */
  presets: { value: string; label: string }[];
  value: DateValue;
  onChange: (next: DateValue) => void;
  errors?: { from?: string; to?: string };
}) {
  return (
    <div className={s.dateGroup}>
      <SelectField
        label={label}
        options={presets}
        value={value.mode}
        onChange={(e) => onChange({ ...value, mode: e.target.value as DateMode })}
      />
      {value.mode === "date" ? (
        <TextField
          label={T.filters.on(label)}
          type="date"
          value={value.from}
          error={errors.from}
          onChange={(e) => onChange({ ...value, from: e.target.value, to: e.target.value })}
        />
      ) : null}
      {value.mode === "range" ? (
        <>
          <TextField
            label={T.filters.fromDate(label)}
            type="date"
            value={value.from}
            error={errors.from}
            onChange={(e) => onChange({ ...value, from: e.target.value })}
          />
          <TextField
            label={T.filters.toDate(label)}
            type="date"
            value={value.to}
            error={errors.to}
            onChange={(e) => onChange({ ...value, to: e.target.value })}
          />
        </>
      ) : null}
    </div>
  );
}
