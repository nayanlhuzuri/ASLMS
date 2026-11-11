/**
 * Office names in place of codes (design portal-names-and-labels, decisions 5 and 8), as pure functions over the map
 * `useOfficeNames()` gives (`GET /reference/offices`). The kit's `OfficeName` is the component form.
 */
import type { OfficeNameMap } from "./api/types";

/** The name of `code`: a payload `name` wins, then the map's name, else the code itself; "—" for no code. Never invented. */
export function officeName(code: string | null | undefined, map: OfficeNameMap | undefined, name?: string | null): string {
  if (!code) return name || "—";
  return name || map?.get(code)?.name || code;
}

export interface NamedOption {
  value: string;
  label: string;
}

/**
 * Department picker options (decision 8): the name alone, sorted by name so a cut-off select shows the start of the
 * name; when two options share a name, both get " (CODE)" after it. The value stays the code.
 */
export function nameOptions(items: readonly { code: string; name: string }[], exclude: readonly (string | null | undefined)[] = []): NamedOption[] {
  const kept = items.filter((d) => !exclude.includes(d.code));
  const counts = new Map<string, number>();
  for (const d of kept) counts.set(d.name, (counts.get(d.name) ?? 0) + 1);
  return kept
    .map((d) => ({ value: d.code, label: (counts.get(d.name) ?? 0) > 1 ? `${d.name} (${d.code})` : d.name || d.code }))
    .sort((a, b) => a.label.localeCompare(b.label) || a.value.localeCompare(b.value));
}
