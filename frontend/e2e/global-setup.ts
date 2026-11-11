/**
 * Makes the run directory `<UICHECK_OUT or /out>/<YYYYMMDD-HHMM>` and passes it to the workers. In boxes mode (design
 * portal-navy-cream, decision 16) it also fixes the run's pinned instant, `UICHECK_CLOCK`, once for every worker.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { boxesEnabled, clockInstant } from "./boxes";

export default function globalSetup(): void {
  const now = new Date(Date.now() + 5.5 * 3600_000); // IST, as the portal's dates
  const stamp = now.toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
  const dir = join(process.env.UICHECK_OUT ?? "/out", stamp);
  mkdirSync(join(dir, "results"), { recursive: true });
  process.env.UICHECK_RUN_DIR = dir;
  process.env.UICHECK_STARTED = String(Date.now());
  if (boxesEnabled()) {
    process.env.UICHECK_CLOCK = clockInstant();
    mkdirSync(join(dir, "boxes"), { recursive: true });
  }
}
