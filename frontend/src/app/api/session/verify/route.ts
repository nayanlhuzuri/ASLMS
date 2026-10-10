import { verify } from "@/server/handlers";
import { withLog } from "@/server/log";

export const dynamic = "force-dynamic";

export const POST = withLog(verify);
