// The Compose health check: answers without calling the API (design portal-shell, decision 20).
export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
