import { NextResponse, type NextRequest } from "next/server";
import { noStore, postBackend, readJson, str } from "@/lib/server/relay";

export const dynamic = "force-dynamic";

/**
 * Sends a new one-time password for an earlier sign-in or password-reset step. The backend allows it once every
 * two minutes (it answers 429 with `details.retry_after` before that) and the previous code stops working.
 */
export async function POST(req: NextRequest) {
  const parsed = await readJson(req);
  if (!parsed.ok) return parsed.res;
  const { status, body } = await postBackend(req, "/auth/otp/resend", {
    challenge_id: str(parsed.data.challenge_id),
  });
  return noStore(NextResponse.json(body, { status }));
}
