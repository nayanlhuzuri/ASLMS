"use client";

import type { Office } from "@/lib/types";
import { Field, Select } from "../ui/Field";

/** The central operator acts for a department; this picks which one. */
export function DepartmentPicker({
  departments,
  value,
  onChange,
  label = "Act for department",
}: {
  departments: Office[];
  value: string;
  onChange: (id: string) => void;
  label?: string;
}) {
  return (
    <Field label={label} className="no-print">
      <Select value={value} onChange={(e) => onChange(e.target.value)} style={{ minWidth: 280 }}>
        <option value="">Choose a department</option>
        {departments.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} ({d.code})
          </option>
        ))}
      </Select>
    </Field>
  );
}
