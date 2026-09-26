import { NextResponse, type NextRequest } from "next/server";
import { noStore, postBackend, readJson, str } from "@/lib/server/relay";

export const dynamic = "force-dynamic";

/** Sets a new password with the OTP from the forgotten-password e-mail. */
export async function POST(req: NextRequest) {
  const parsed = await readJson(req);
  if (!parsed.ok) return parsed.res;
  const { status, body } = await postBackend(req, "/auth/password/reset", {
    challenge_id: str(parsed.data.challenge_id),
    code: str(parsed.data.code).trim(),
    new_password: str(parsed.data.new_password),
  });
  return noStore(NextResponse.json(body, { status }));
}
