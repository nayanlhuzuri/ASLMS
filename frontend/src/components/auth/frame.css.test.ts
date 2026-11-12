// @vitest-environment node
/**
 * The sign-in frame's stylesheet and fonts, read statically (design signin-gold-emblem, decisions 4, 8, 10, 13, 14 and
 * 15): the emblem's motion from the tokens, still under reduced motion and when paused, the gold only as tokens of
 * globals.css, the brand row gone, and the two Noto fonts imported only by the public pages' frame.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const read = (...parts: string[]) => readFileSync(join(SRC, ...parts), "utf-8");
const uncommented = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

const auth = uncommented(read("components", "auth", "auth.module.css"));
const globals = uncommented(read("app", "globals.css"));

/** The declarations of the first rule whose selector list is exactly `selector`. */
function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const m = new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  if (!m) throw new Error(`no rule ${selector}`);
  return m[1]!;
}

describe("the emblem's motion (decisions 4, 5 and 13)", () => {
  it("the four animations run on var(--turn) and var(--sweep), never on literal seconds", () => {
    expect(rule(auth, ".spinner")).toMatch(/animation:\s*emblem-turn var\(--turn\) linear infinite/);
    expect(rule(auth, ".gold")).toMatch(/animation:\s*emblem-sheen var\(--turn\) linear infinite/);
    expect(rule(auth, ".shadow")).toMatch(/animation:\s*emblem-shadow calc\(var\(--turn\) \/ 2\)/);
    expect(rule(auth, ".goldText")).toMatch(/animation:\s*gold-sweep var\(--sweep\) ease-in-out infinite/);
    expect(auth).not.toMatch(/animation[^;]*\b\d+(\.\d+)?m?s\b/);
  });

  it("--turn is 10s and --sweep 8s, and both are 0ms in the reduced-motion block", () => {
    const root = globals.slice(globals.indexOf(":root {"), globals.indexOf("}", globals.indexOf(":root {")));
    expect(root).toMatch(/--turn:\s*10s;/);
    expect(root).toMatch(/--sweep:\s*8s;/);
    const reduced = globals.slice(globals.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/--turn:\s*0ms;/);
    expect(reduced).toMatch(/--sweep:\s*0ms;/);
  });

  it("the faces are two-sided: preserve-3d, hidden back faces, the back pre-rotated, perspective on the stage", () => {
    expect(rule(auth, ".spinner")).toMatch(/transform-style:\s*preserve-3d/);
    expect(rule(auth, ".spinner")).toMatch(/will-change:\s*transform/);
    expect(rule(auth, ".face")).toMatch(/(^|\s)backface-visibility:\s*hidden/);
    expect(rule(auth, ".face")).toMatch(/-webkit-backface-visibility:\s*hidden/);
    expect(rule(auth, ".back")).toMatch(/transform:\s*rotateY\(180deg\)/);
    expect(rule(auth, ".stage")).toMatch(/perspective:\s*900px/);
  });

  it("the gold is the gradient token under the cut-out's mask, with and without the -webkit- prefix", () => {
    const gold = rule(auth, ".gold");
    expect(gold).toMatch(/background:\s*var\(--gold\)/);
    expect(gold).toMatch(/-webkit-mask:\s*var\(--emblem-mask\) center \/ contain no-repeat/);
    expect(gold).toMatch(/(^|\s)mask:\s*var\(--emblem-mask\) center \/ contain no-repeat/);
    // the CSS module carries no file path: brand.ts names the cut-out
    expect(auth).not.toMatch(/url\(/);
  });
});

describe("the still states (decisions 8 and 14)", () => {
  it(".motionBtn is hidden under prefers-reduced-motion: reduce", () => {
    const block = auth.slice(auth.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toMatch(/^@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.motionBtn\s*\{\s*display:\s*none;/);
  });

  it("the paused state removes the four animations", () => {
    const paused = /((?:\.emblemBlock\[data-motion="paused"\] \.[a-zA-Z]+,?\s*)+)\{\s*animation:\s*none;\s*\}/.exec(auth);
    expect(paused).not.toBeNull();
    const targets = [...paused![1]!.matchAll(/\] \.([a-zA-Z]+)/g)].map((m) => m[1]).sort();
    expect(targets).toEqual(["gold", "goldText", "shadow", "spinner"]);
  });
});

describe("the gold tokens and the brand row (decisions 10 and 13)", () => {
  it("the gold values live in globals.css as --gold* tokens", () => {
    for (const [name, value] of [
      ["--gold-deep", "#7a5a14"],
      ["--gold-mid", "#c99a2e"],
      ["--gold-light", "#f7e08a"],
      ["--gold-shine", "#fff6c9"],
      ["--gold-line", "rgba(246, 196, 142, 0.28)"],
      ["--gold-halo", "rgba(246, 196, 142, 0.22)"],
    ]) {
      expect(globals).toContain(`${name}: ${value};`);
    }
    expect(globals).toMatch(/--gold:\s*linear-gradient\(115deg, var\(--gold-deep\) 0%/);
  });

  it("auth.module.css names no gold hex and no colour literal", () => {
    expect(auth).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(auth).not.toMatch(/\brgba?\(/i);
  });

  it(".brandRow and its rules no longer exist", () => {
    for (const name of [".brandRow", ".lockup", ".gov", ".name"]) expect(auth).not.toMatch(new RegExp(`\\${name}\\b`));
  });
});

/** Every .ts, .tsx and .css file under a directory. */
function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...sources(full));
    else if (/\.(tsx?|css)$/.test(name)) out.push(full);
  }
  return out;
}

describe("the Noto fonts load only on the public pages (decision 15)", () => {
  it("AuthFrame.tsx imports the two @fontsource/noto-serif-* stylesheets", () => {
    const frame = read("components", "auth", "AuthFrame.tsx");
    expect(frame).toContain('import "@fontsource/noto-serif-bengali/bengali-600.css";');
    expect(frame).toContain('import "@fontsource/noto-serif-devanagari/devanagari-500.css";');
  });

  it("no portal page, nor the root layout, nor globals.css imports them", () => {
    const files = [...sources(join(SRC, "app", "(portal)")), join(SRC, "app", "layout.tsx"), join(SRC, "app", "globals.css")];
    expect(files.length).toBeGreaterThan(3);
    for (const file of files) expect(readFileSync(file, "utf-8"), file).not.toMatch(/noto-serif/);
  });
});
