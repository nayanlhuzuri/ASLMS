import { NextResponse, type NextRequest } from "next/server";
import { noStore, postBackend, readJson, str } from "@/lib/server/relay";

export const dynamic = "force-dynamic";

/** Step 1: e-mail and password. Returns the OTP challenge id; no token is issued yet. */
export async function POST(req: NextRequest) {
  const parsed = await readJson(req);
  if (!parsed.ok) return parsed.res;
  const { status, body } = await postBackend(req, "/auth/login", {
    email: str(parsed.data.email).trim(),
    password: str(parsed.data.password),
  });
  return noStore(NextResponse.json(body, { status }));
}
