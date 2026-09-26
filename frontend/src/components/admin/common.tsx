"use client";

import { isOperator } from "@/lib/roles";
import type { Me, Office } from "@/lib/types";
import { Field, Select } from "../ui/Field";

/** Offices the caller may administer: all for the central operator, the own department subtree otherwise. */
export function adminOffices(me: Me, offices: Office[]): Office[] {
  const usable = offices.filter((o) => o.is_active && (o.kind === "department" || o.kind === "directorate" || o.kind === "section"));
  if (isOperator(me)) return usable;
  const dept = me.department;
  if (!dept) return [];
  return usable.filter((o) => o.path === dept.path || o.path.startsWith(`${dept.path}/`));
}

export function depth(o: Office): number {
  return o.path.split("/").length - 1;
}

export function OfficeSelect({
  label,
  value,
  onChange,
  offices,
  required,
  placeholder = "Choose an office",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  offices: Office[];
  required?: boolean;
  placeholder?: string;
}) {
  return (
    <Field label={label}>
      <Select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        <option value="">{placeholder}</option>
        {offices.map((o) => (
          <option key={o.id} value={o.id}>
            {"  ".repeat(depth(o))}
            {o.name} ({o.code})
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function officeName(byId: Map<string, Office>, id: string): string {
  const o = byId.get(id);
  return o ? o.name : "Unknown office";
}
