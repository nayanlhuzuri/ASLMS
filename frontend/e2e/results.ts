/** The per-test result files the spec writes and the teardown gathers (design portal-ui-polish, decision 22). */
import { writeFileSync } from "node:fs";
import { join } from "node:path";

export interface Finding {
  route: string;
  width: number;
  kind: string;
  element: string;
  detail: string;
}

export interface ResultFile {
  /** The route, or the route and the interaction state (`/system ?api=cnr`). */
  name: string;
  width: number;
  /** The screenshot, relative to the run directory. */
  screenshot: string | null;
  /** Where a redirect page went. */
  redirect: string | null;
  findings: Finding[];
}

export function runDir(): string {
  const dir = process.env.UICHECK_RUN_DIR;
  if (!dir) throw new Error("UICHECK_RUN_DIR is not set (the global setup makes it)");
  return dir;
}

export function slug(name: string): string {
  return (name.replace(/^\//, "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "") || "dashboard").toLowerCase();
}

export function writeResult(result: ResultFile): void {
  writeFileSync(join(runDir(), "results", `${slug(result.name)}-${result.width}.json`), JSON.stringify(result));
}
