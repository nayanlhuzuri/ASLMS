/**
 * Helpers of the department mapping screens (design portal-mapping, decisions 3, 5, 7 and 8). A plain module, so a
 * server page or a unit test may import it. Every check here is a convenience: the API checks again and decides.
 */
import { ApiError } from "./api/client";

/** The API's `CNR_RE`: four letters and twelve digits. */
export const CNR_PATTERN = /^[A-Z]{4}\d{12}$/;

/** The CNR as sent: trimmed and upper-cased. */
export function normaliseCnr(value: string): string {
  return value.trim().toUpperCase();
}

export function isCnr(value: string): boolean {
  return CNR_PATTERN.test(normaliseCnr(value));
}

/**
 * The `weight` part of a rule request (decision 3): nothing when the override input was not changed (the API reads a
 * missing key as "no change" and refuses any `weight` key without `admin.scoring`), `null` to clear it, a number to
 * set it.
 */
export function weightBody(changed: boolean, value: string | number | null): { weight?: number | null } {
  if (!changed) return {};
  if (value === null || (typeof value === "string" && value.trim() === "")) return { weight: null };
  return { weight: Number(value) };
}

/** The root office (the State): the one whose path has no `/`. */
export function isRootOffice(office: { path?: string | null } | null | undefined): boolean {
  return !!office?.path && !office.path.includes("/");
}

/** The depth of an office in the tree (the root is 0). */
export function officeDepth(office: { path: string }): number {
  return office.path.split("/").length - 1;
}

// design partial-code-match, decision 10: the partial counsel-code weight follows the counsel-code weight
export const WEIGHT_KINDS = ["counsel_code", "counsel_code_partial", "name_pattern", "watchlist", "linked_case", "keyword"] as const;
export type WeightKind = (typeof WEIGHT_KINDS)[number];
export const THRESHOLDS = ["strong", "possible"] as const;
export type Threshold = (typeof THRESHOLDS)[number];
export type ScoringField = WeightKind | Threshold;
export const SCORING_FIELDS: readonly ScoringField[] = [...WEIGHT_KINDS, ...THRESHOLDS];

export interface ScoringValues {
  weights: Record<string, number>;
  thresholds: Record<string, number>;
}

/**
 * The browser-side checks of the scoring form (decision 8): each value in (0, 1] and 0 < possible < strong ≤ 1; the
 * partial counsel-code weight at or above Possible, below Strong and below the counsel-code weight (design
 * partial-code-match, decision 12), so a partial match alone is always a possible match.
 */
export function scoringErrors(values: Record<ScoringField, number | string>): Partial<Record<ScoringField, string>> {
  const out: Partial<Record<ScoringField, string>> = {};
  const num = (f: ScoringField) => (typeof values[f] === "string" && String(values[f]).trim() === "" ? NaN : Number(values[f]));
  for (const f of SCORING_FIELDS) {
    const v = num(f);
    if (!Number.isFinite(v) || v <= 0 || v > 1) out[f] = "Enter a number greater than 0 and at most 1.";
  }
  const strong = num("strong");
  const possible = num("possible");
  if (!out.strong && !out.possible && !(possible < strong)) out.possible = "Possible must be below Strong.";
  const partial = num("counsel_code_partial");
  if (!out.counsel_code_partial && !out.strong && !out.possible && !(possible <= partial && partial < strong)) {
    out.counsel_code_partial = "The partial code weight must be at least Possible and below Strong.";
  }
  if (!out.counsel_code_partial && !out.counsel_code && !(partial < num("counsel_code"))) {
    out.counsel_code_partial = "The partial code weight must be below the counsel code weight.";
  }
  return out;
}

/** The value of one field of a stored settings version. */
export function scoringValue(version: ScoringValues, field: ScoringField): number | undefined {
  return (THRESHOLDS as readonly string[]).includes(field) ? version.thresholds[field] : version.weights[field];
}

/** The fields of `version` that differ from the next older version (none for the oldest). */
export function changedFields(version: ScoringValues, older: ScoringValues | null | undefined): ScoringField[] {
  if (!older) return [];
  return SCORING_FIELDS.filter((f) => scoringValue(version, f) !== scoringValue(older, f));
}

/** Three decimals, as the API stores weights. */
export function weightText(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(3);
}

const GIVEN = new Set([400, 403, 404, 409, 500, 503, 504]);

/**
 * The API's refusal shown as given (decisions 4, 5, 7 and 9: "shown as given"): the mapping screens show the
 * server's own message (for example "the office is outside your offices") instead of the portal's fixed text for the
 * status. Sign-in, gate and network errors keep their usual handling.
 */
export function given(error: unknown): unknown {
  if (error instanceof ApiError && GIVEN.has(error.status) && error.message && error.message !== "the request failed") {
    return new ApiError(error.status, "bad_input", error.message, error.extra);
  }
  return error;
}

/** Whether the API refused because it could not tell the department (`office_code is required: …`). */
export function officeRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400 && error.message.startsWith("office_code is required");
}
