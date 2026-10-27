/**
 * No upper-case labels anywhere in the portal (design data-collection-redesign, decision 8; the owner decided it
 * twice): no style sheet sets `text-transform: uppercase`, so every table header, menu group and fact label reads in
 * the Title Case its source string carries, as the navigation template sets `text-transform: none`.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, out);
    else if (/\.(css|tsx?)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

describe("styles (design data-collection-redesign, decision 8)", () => {
  it("no text-transform: uppercase in any style sheet or inline style", () => {
    const found = files(SRC)
      .filter((f) => /text-?transform\s*:\s*["']?uppercase/i.test(readFileSync(f, "utf-8")))
      .map((f) => relative(SRC, f).split(sep).join("/"));
    expect(found).toEqual([]);
  });
});
