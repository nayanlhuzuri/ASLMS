/**
 * The `next` parameter after sign-in (design portal-shell, decision 8): honoured only as a relative path that
 * starts with exactly one `/` (no `//host`, no `/\host`, no scheme); anything else goes to the dashboard.
 */
const BASE = "http://portal.invalid";

export function safeNext(value: string | null | undefined): string {
  if (!value) return "/";
  const v = value.trim();
  if (!v.startsWith("/") || v.startsWith("//") || v.includes("\\")) return "/";
  if ([...v].some((ch) => ch.charCodeAt(0) < 32)) return "/";
  try {
    const url = new URL(v, BASE);
    if (url.origin !== BASE) return "/";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/";
  }
}
