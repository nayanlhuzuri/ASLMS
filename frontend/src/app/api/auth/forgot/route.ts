import { NextResponse, type NextRequest } from "next/server";
import { noStore, postBackend, readJson, str } from "@/lib/server/relay";

export const dynamic = "force-dynamic";

/** Forgotten password: sends an OTP to the e-mail address and returns the challenge id. */
export async function POST(req: NextRequest) {
  const parsed = await readJson(req);
  if (!parsed.ok) return parsed.res;
  const { status, body } = await postBackend(req, "/auth/password/forgot", { email: str(parsed.data.email).trim() });
  return noStore(NextResponse.json(body, { status }));
}
