import { withLog } from "@/server/log";
import { relay } from "@/server/relay";

export const dynamic = "force-dynamic";

const handle = withLog(relay);

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST, handle as PUT };
