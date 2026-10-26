/**
 * References in portal URLs (design portal-cases, decision 1): a `ref_no` is written with `-` for `/` (the form the
 * notification mails use, `<PORTAL_BASE_URL>/cases/<ref>`); the API resolves that form, an id or a CNR.
 */
export function refPath(ref: string): string {
  return ref.replaceAll("/", "-");
}

/** The case page of a `ref_no` (or a CNR), optionally one of its tabs. */
export function casePath(ref: string, tab?: string): string {
  const base = `/cases/${encodeURIComponent(refPath(ref))}`;
  return tab ? `${base}/${tab}` : base;
}

/** The API path of a case (through the relay, which refuses an encoded `/`): always the dash form. */
export function apiCasePath(ref: string, tail?: string): string {
  const base = `/cases/${encodeURIComponent(refPath(ref))}`;
  return tail ? `${base}/${tail}` : base;
}

/**
 * The address to replace an outdated case address with (design case-ref-court-prefix, decision 20), or null. Only an
 * address whose `[ref]` is a `ref_no` form (`ASLMS-…` or `ASLMS/…`) that differs from the case's current number is
 * replaced; the tab and the query string are kept. Addresses by id or CNR are left alone. No prefix rule is repeated
 * here: the API resolves an old number and answers with the current `ref_no`.
 */
export function currentCaseHref(pathname: string, search: string, caseRef: string, refNo: string): string | null {
  const ref = caseRef.trim().toUpperCase();
  if (!ref.startsWith("ASLMS-") && !ref.startsWith("ASLMS/")) return null;
  if (refPath(caseRef.trim()) === refPath(refNo)) return null;
  const parts = pathname.split("/");
  // `/cases/<ref>/<tab…>`: everything after the ref segment is kept
  const rest = parts[1] === "cases" && parts.length > 3 ? parts.slice(3).filter(Boolean).join("/") : "";
  const query = search.replace(/^\?/, "");
  return `${casePath(refNo, rest || undefined)}${query ? `?${query}` : ""}`;
}
