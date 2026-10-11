import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseStatus, STATUSES } from "./tickets";

describe("ticket statuses", () => {
  it("accepts every known status and defaults the rest to open", () => {
    for (const st of STATUSES) expect(parseStatus(st)).toBe(st);
    expect(parseStatus(undefined)).toBe("open");
    expect(parseStatus("")).toBe("open");
    expect(parseStatus("closed")).toBe("open");
  });

  it("is plain data, not a client module (a server page imports it)", () => {
    const src = readFileSync(join(__dirname, "tickets.ts"), "utf8");
    expect(src).not.toMatch(/^\s*["']use client["']/m);
  });
});
