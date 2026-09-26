import { NextResponse, type NextRequest } from "next/server";
import { postBackend } from "@/lib/server/relay";
import { clearSessionCookies, csrfOk, errorBody, REFRESH_COOKIE } from "@/lib/server/session";

export const dynamic = "force-dynamic";

/** Revokes the refresh token at the backend and clears both cookies. */
export async function POST(req: NextRequest) {
  if (!csrfOk(req)) return NextResponse.json(errorBody("forbidden", "Request refused."), { status: 403 });
  const rt = req.cookies.get(REFRESH_COOKIE)?.value;
  if (rt) await postBackend(req, "/auth/logout", { refresh_token: rt });
  const res = NextResponse.json({ ok: true });
  clearSessionCookies(res);
  res.headers.set("cache-control", "no-store");
  return res;
}
