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
