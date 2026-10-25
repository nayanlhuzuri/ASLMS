/**
 * The Audit log screen's pure helpers (design portal-audit-health, decisions 3-6): the URL's filters as sent to
 * `GET /audit`, the quick periods, the browser's checks, the grouped action list, the before / after rows and which
 * field shows an API refusal. A plain module, so the server pages may import its values.
 */
import { addDays } from "./format";
import { T } from "./messages";
import type { Params } from "./params";

/** The ten filters, named as the API names them, so a screen URL and an API URL carry the same filters. */
export const AUDIT_PARAMS = [
  "user",
  "actor",
  "about_user",
  "case",
  "office",
  "action",
  "entity_type",
  "entity_id",
  "from",
  "to",
] as const;

export type AuditParam = (typeof AUDIT_PARAMS)[number];

/** The page size of the screen (the API's default; at most 200). */
export const AUDIT_PAGE = 50;

/** The non-empty filters of the URL, trimmed, as sent to the API; any other name is dropped. */
export function auditParams(params: Params): Params {
  const out: Params = {};
  for (const name of AUDIT_PARAMS) {
    const value = params[name]?.trim();
    if (value) out[name] = value;
  }
  return out;
}

export const PERIOD_CHOICES = ["any", "today", "last_7", "last_30", "custom"] as const;
export type PeriodChoice = (typeof PERIOD_CHOICES)[number];

/** The IST dates of a quick choice, today included; "Any time" and "Choose dates" give none. */
export function periodChoice(choice: PeriodChoice, today: string): { from: string; to: string } | null {
  switch (choice) {
    case "today":
      return { from: today, to: today };
    case "last_7":
      return { from: addDays(today, -6), to: today };
    case "last_30":
      return { from: addDays(today, -29), to: today };
    default:
      return null;
  }
}

/** The quick choice the URL's dates stand for. */
export function choiceOf(from: string | undefined, to: string | undefined, today: string): PeriodChoice {
  if (!from && !to) return "any";
  for (const c of ["today", "last_7", "last_30"] as const) {
    const p = periodChoice(c, today)!;
    if (p.from === from && p.to === to) return c;
  }
  return "custom";
}

export interface FilterForm {
  actor?: string;
  from?: string;
  to?: string;
  entity_id?: string;
}

export interface FilterProblems {
  actor?: "length";
  period?: "order" | "future";
  entity_id?: "uuid";
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The browser's checks (decision 4), so the API's 422 is not reached: "Name contains" 2 to 100 characters, `to` not
 * before `from`, `from` not after today, the record id a UUID. Null when the form may be sent.
 */
export function checkFilters(form: FilterForm, today: string): FilterProblems | null {
  const problems: FilterProblems = {};
  const actor = form.actor?.trim() ?? "";
  if (actor && (actor.length < 2 || actor.length > 100)) problems.actor = "length";
  if (form.from && form.to && form.to < form.from) problems.period = "order";
  else if (form.from && form.from > today) problems.period = "future";
  const id = form.entity_id?.trim() ?? "";
  if (id && !UUID.test(id)) problems.entity_id = "uuid";
  return Object.keys(problems).length ? problems : null;
}

export interface ActionGroup {
  /** The group's prefix with its dot (`custody.`), sent for "All … actions"; null for a code without a dot. */
  prefix: string | null;
  label: string;
  codes: string[];
}

/** The action codes grouped by the part before the first dot, groups by label, codes sorted. */
/** The name of an action where it has one (design portal-ui-polish-2, decision 13), else its code. */
export function actionName(code: string): string {
  return T.audit.actionNames[code] ?? code;
}

export function actionGroups(codes: readonly string[], groupLabels: Record<string, string>): ActionGroup[] {
  const groups = new Map<string, ActionGroup>();
  for (const code of new Set(codes)) {
    const dot = code.indexOf(".");
    const key = dot > 0 ? code.slice(0, dot) : code;
    const id = dot > 0 ? `${key}.` : `=${code}`;
    let group = groups.get(id);
    if (!group) {
      group = { prefix: dot > 0 ? `${key}.` : null, label: groupLabels[key] ?? key, codes: [] };
      groups.set(id, group);
    }
    group.codes.push(code);
  }
  const out = [...groups.values()];
  for (const g of out) g.codes.sort();
  return out.sort((a, b) => a.label.localeCompare(b.label) || (a.prefix ?? "").localeCompare(b.prefix ?? ""));
}

export interface DiffRow {
  key: string;
  before: unknown;
  after: unknown;
  changed: boolean;
}

/** The key a value that is not an object is shown under. */
export const VALUE_KEY = "(value)";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value === null || value === undefined) return {};
  return isPlainObject(value) ? value : { [VALUE_KEY]: value };
}

function nullish(value: unknown): boolean {
  return value === null || value === undefined;
}

/** Equal by value (nested objects and lists compared member by member); `null` and absent are equal. */
export function sameValue(a: unknown, b: unknown): boolean {
  if (nullish(a) || nullish(b)) return nullish(a) && nullish(b);
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => sameValue(x, b[i]));
  }
  if (isPlainObject(a) || isPlainObject(b)) {
    if (!isPlainObject(a) || !isPlainObject(b)) return false;
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) if (!sameValue(a[k], b[k])) return false;
    return true;
  }
  return a === b;
}

/** One row per key of the union of `before` and `after`, in the order the keys appear, marked where they differ. */
export function diffRows(before: unknown, after: unknown): DiffRow[] {
  const b = asRecord(before);
  const a = asRecord(after);
  const keys: string[] = [];
  for (const k of [...Object.keys(b), ...Object.keys(a)]) if (!keys.includes(k)) keys.push(k);
  return keys.map((key) => ({ key, before: b[key], after: a[key], changed: !sameValue(b[key], a[key]) }));
}

/** A withheld text as the log stores it: exactly `{length, sha256}` (note bodies, custody remarks). */
export function isTextDigest(value: unknown): value is { length: number; sha256: string } {
  if (!isPlainObject(value)) return false;
  const keys = Object.keys(value);
  return keys.length === 2 && keys.includes("length") && keys.includes("sha256");
}

export type ErrorField = "user" | "about_user" | "actor" | "case" | "office" | "period";

/** The fields that show an API refusal (decision 4); empty when the banner shows it. */
export function fieldOfError(code: string, sent: Params): ErrorField[] {
  switch (code) {
    case "unknown_user": {
      const out: ErrorField[] = [];
      if (sent.user) out.push("user");
      if (sent.about_user) out.push("about_user");
      return out;
    }
    case "not_found":
      return sent.case ? ["case"] : [];
    case "bad_office":
      return ["office"];
    case "bad_period":
      return ["period"];
    case "bad_actor":
      return ["actor"];
    default:
      return [];
  }
}
