/** Makes the run directory `<UICHECK_OUT or /out>/<YYYYMMDD-HHMM>` and passes it to the workers. */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

export default function globalSetup(): void {
  const now = new Date(Date.now() + 5.5 * 3600_000); // IST, as the portal's dates
  const stamp = now.toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
  const dir = join(process.env.UICHECK_OUT ?? "/out", stamp);
  mkdirSync(join(dir, "results"), { recursive: true });
  process.env.UICHECK_RUN_DIR = dir;
  process.env.UICHECK_STARTED = String(Date.now());
}
