// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { T } from "@/lib/messages";

/** Owner decision (21 Oct 2026): the portal names only ASLMS and the Government of Assam, never the agencies that build it. */
const AGENCIES = /semt|amtron/i;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("branding", () => {
  it("the application's name is the Assam State Litigation Management System", () => {
    expect(T.portal).toBe("ASLMS");
    expect(T.portalLong).toBe("Assam State Litigation Management System");
  });

  it("no source file or public asset of the portal names SeMT or AMTRON", () => {
    const root = process.cwd();
    const offenders = [...files(join(root, "src")), ...files(join(root, "public"))]
      .filter((f) => /\.(tsx?|css|json|svg|txt|html)$/.test(f) && !f.endsWith("branding.test.ts"))
      .filter((f) => AGENCIES.test(readFileSync(f, "utf-8")));
    expect(offenders).toEqual([]);
  });
});
