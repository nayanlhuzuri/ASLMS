/**
 * Query-string filters (design portal-cases, decision 1), shared by the server pages and the client lists. Kept in a
 * plain module: a server page that imports a value from a `"use client"` module receives a client reference, not the
 * value (the `/admin/tickets` lesson of 11 Oct).
 */
export type Params = Record<string, string | undefined>;

export const PAGE = 50;

/** Plain values of a Next `searchParams` object (the first of repeated keys). */
export function plainParams(sp: Record<string, string | string[] | undefined>): Params {
  const out: Params = {};
  for (const [k, v] of Object.entries(sp)) out[k] = Array.isArray(v) ? v[0] : v;
  return out;
}

export function queryString(params: Params): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, v);
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export function offsetOf(params: Params): number {
  const n = Number(params.offset ?? 0);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}
