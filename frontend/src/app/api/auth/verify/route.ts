import { NextResponse, type NextRequest } from "next/server";
import { noStore, postBackend, readJson, str } from "@/lib/server/relay";
import { setSessionCookies, type Tokens } from "@/lib/server/session";

export const dynamic = "force-dynamic";

/** Step 2: the one-time password. On success the tokens go into httpOnly cookies, never to the browser. */
export async function POST(req: NextRequest) {
  const parsed = await readJson(req);
  if (!parsed.ok) return parsed.res;
  const { status, body } = await postBackend(req, "/auth/verify", {
    challenge_id: str(parsed.data.challenge_id),
    code: str(parsed.data.code).trim(),
  });
  if (status !== 200 || !body || typeof body !== "object" || !("access_token" in body)) {
    return noStore(NextResponse.json(body, { status: status === 200 ? 502 : status }));
  }
  const res = NextResponse.json({ ok: true });
  setSessionCookies(res, body as Tokens);
  return noStore(res);
}
