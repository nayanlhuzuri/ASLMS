/**
 * The portal's three label helpers (design portal-names-and-labels, decisions 10 and 14), so every code and every
 * server label reaches the screen the same way.
 *
 * - `labelFor(map, code)`: the portal's own label of a code, else the code read as words in Title Case. A code never
 *   shows as a lowercase code.
 * - `serverLabel(text)`: a label that comes from the server (`ref_*` tables, `*_label` fields, stage and timeline
 *   labels, the dashboard attention title) in Title Case when shown. `titleCase` is idempotent, so a label already in
 *   Title Case is unchanged. Never for names, sentences or data.
 * - `labelOf(list, code)`: the server list's label through `serverLabel`, else `labelFor`.
 */
import { titleCase } from "./titleCase";

/**
 * The label of `code` in `map` (the map is read first, so an "" option such as the date presets' "Any" keeps its
 * label); "—" for no code; otherwise the code with `_` and `.` read as spaces, in Title Case.
 */
export function labelFor(map: Readonly<Record<string, string>> | undefined, code: string | null | undefined): string {
  if (code === null || code === undefined) return "—";
  const label = map?.[code];
  if (label) return label;
  if (code === "") return "—";
  return titleCase(code.replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim());
}

/** A server label in Title Case (decision 10); an empty value stays empty. */
export function serverLabel(text: string): string;
export function serverLabel(text: string | null | undefined): string | null | undefined;
export function serverLabel(text: string | null | undefined): string | null | undefined {
  if (!text) return text;
  return titleCase(text);
}

/** The label of `code` in a server list (`GET /reference/labels`) through `serverLabel`, else `labelFor`. */
export function labelOf(list: readonly { code: string; label: string }[] | undefined, code: string | null | undefined): string {
  if (!code) return "—";
  const label = list?.find((x) => x.code === code)?.label;
  return label ? serverLabel(label) : labelFor(undefined, code);
}
