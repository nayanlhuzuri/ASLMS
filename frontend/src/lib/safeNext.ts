/** Only same-site paths are accepted as a post-login destination (no open redirects). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next.startsWith("/api/") || next.startsWith("/login") || next.startsWith("/forgot")) return "/";
  return next;
}
