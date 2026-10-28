import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const globals = readFileSync(join(SRC, "app", "globals.css"), "utf-8");

/** The `:root` tokens of globals.css (the first block, before the reduced-motion override). */
function tokens(): Record<string, string> {
  const root = globals.slice(globals.indexOf(":root {"), globals.indexOf("}", globals.indexOf(":root {")));
  const out: Record<string, string> = {};
  for (const m of root.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) out[m[1]!] = m[2]!.trim();
  return out;
}

const TOKENS = tokens();

function hex(name: string): string {
  let value = TOKENS[name];
  for (let i = 0; value?.startsWith("var(") && i < 5; i += 1) value = TOKENS[value.slice(4, -1)];
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error(`${name} is not a hex colour: ${value}`);
  return value;
}

function luminance(colour: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(colour.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a! + 0.05) / (b! + 0.05);
}

/** The earlier token names, aliases during rounds 1-4 and removed in round 5 (decision 11). */
const REMOVED_ALIASES = [
  "--navy-900",
  "--navy-800",
  "--navy-700",
  "--navy-100",
  "--gold-600",
  "--gold-100",
  "--ink",
  "--ink-muted",
  "--line",
  "--page",
  "--danger",
  "--danger-bg",
  "--success",
  "--success-bg",
  "--warning",
  "--warning-bg",
  "--focus",
  "--font-serif",
  "--space-1",
  "--space-2",
  "--space-3",
  "--space-4",
  "--space-5",
  "--space-6",
  "--space-7",
  "--text-xs",
  "--text-sm",
  "--text-md",
  "--text-lg",
  "--text-xl",
  "--text-2xl",
  "--radius",
  "--shadow",
  "--sidebar-width",
];

/** Every file under `src/` with one of the extensions, as paths relative to `src/` with forward slashes. */
function sources(extensions: string[], dir = SRC): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...sources(extensions, path));
    else if (extensions.some((e) => name.endsWith(e))) out.push(relative(SRC, path).split("\\").join("/"));
  }
  return out.sort();
}

/** The uses of a removed alias in a stylesheet or a component (`var(--line)`, `var(--focus, #fff)`). */
function aliasUses(text: string): string[] {
  const names = REMOVED_ALIASES.map((a) => a.slice(2)).join("|");
  return [...text.matchAll(new RegExp(`var\\(--(${names})(?=[,)\\s])`, "g"))].map((m) => m[0]);
}

describe("design tokens (design portal-ui-redesign, decision 11)", () => {
  it("carry the v4 values", () => {
    expect(TOKENS["--accent"]).toBe("#1d4ed8");
    expect(TOKENS["--bg"]).toBe("#f5f7fa");
    expect(TOKENS["--control-h"]).toBe("36px");
    expect([1, 2, 3, 4, 5, 6, 7].map((n) => TOKENS[`--s${n}`])).toEqual(["4px", "8px", "12px", "16px", "24px", "32px", "48px"]);
    expect(["xs", "sm", "md", "lg", "xl", "2xl", "3xl"].map((n) => TOKENS[`--t-${n}`])).toEqual([
      "12px",
      "13px",
      "14px",
      "16px",
      "20px",
      "24px",
      "30px",
    ]);
    expect([TOKENS["--fast"], TOKENS["--med"], TOKENS["--slow"]]).toEqual(["150ms", "220ms", "320ms"]);
    expect([TOKENS["--lead-w"], TOKENS["--date-w"], TOKENS["--icon-w"]]).toEqual(["96px", "48px", "20px"]);
  });

  it("no longer define the deprecated aliases (round 5 removed them)", () => {
    for (const alias of REMOVED_ALIASES) expect(TOKENS[alias]).toBeUndefined();
  });

  it("turn motion off under prefers-reduced-motion", () => {
    const reduced = globals.slice(globals.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/--fast:\s*0ms/);
    expect(reduced).toMatch(/--med:\s*0ms/);
    expect(reduced).toMatch(/--slow:\s*0ms/);
    expect(reduced).toMatch(/animation:\s*none !important/);
    expect(reduced).toMatch(/transition:\s*none !important/);
  });

  // decision 11: every text and background pair meets WCAG 2.1 AA (4.5:1)
  it.each([
    ["--text", "--bg"],
    ["--text", "--surface"],
    ["--text-2", "--bg"],
    ["--text-2", "--surface"],
    ["--text-3", "--bg"],
    ["--text-3", "--surface"],
    ["--text-3", "--surface-2"],
    ["--accent", "--surface"],
    ["--accent", "--bg"],
    ["--red-text", "--surface"],
    ["--red-text", "--bg"],
    // badges: neutral, red, amber, green, blue
    ["--text-2", "--slate-soft"],
    ["--red-text", "--red-soft"],
    ["--amber", "--amber-soft"],
    ["--green", "--green-soft"],
    ["--accent", "--accent-soft"],
    // the public pages' panel (round 5): every text colour on both ends of its gradient
    ["--panel-text", "--panel-from"],
    ["--panel-text", "--panel-to"],
    ["--panel-strong", "--panel-from"],
    ["--panel-muted", "--panel-from"],
    ["--panel-muted", "--panel-to"],
    ["--panel-accent", "--panel-from"],
    ["--panel-accent", "--panel-to"],
  ])("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(hex(fg), hex(bg))).toBeGreaterThanOrEqual(4.5);
  });

  it("white text on the accent (the primary button) is at least 4.5:1", () => {
    expect(contrast("#ffffff", hex("--accent"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#ffffff", hex("--accent-hover"))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("the next hearing badge's colours (design next-hearing-highlight, decisions 4, 5 and 13)", () => {
  it("defines --on-red, the text on a solid red fill", () => {
    expect(TOKENS["--on-red"]).toBe("#ffffff");
  });

  it.each([
    // strong, soft, warning (Date Passed), muted (No Date Yet, Disposed) on the surface and the zebra row
    ["--on-red", "--red"],
    ["--amber", "--amber-soft"],
    ["--amber", "--slate-soft"],
    ["--text-3", "--surface"],
    ["--text-3", "--surface-2"],
    ["--text", "--surface"],
    ["--text-2", "--surface"],
    // a suggested date's outline on the surface
    ["--red-text", "--surface"],
    ["--amber", "--surface"],
  ])("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(hex(fg), hex(bg))).toBeGreaterThanOrEqual(4.5);
  });

  it("hearingDate.module.css takes every colour from a token, so a dark theme of the tokens covers it", () => {
    const css = readFileSync(join(SRC, "components/ui/hearingDate.module.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toMatch(/\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i);
    const colourDecls = [...css.matchAll(/(?:^|[;{\s])(color|background(?:-color)?|border(?:-[a-z]+)?(?:-color)?|outline(?:-color)?|fill|stroke)\s*:\s*([^;}]+)/g)];
    expect(colourDecls.length).toBeGreaterThan(5);
    const NAMED = /\b(white|black|red|green|blue|amber|orange|yellow|grey|gray|silver|navy|maroon|purple)\b/i;
    for (const [, prop, value] of colourDecls) {
      const bare = value!.replace(/var\(--[a-z0-9-]+\)/g, "");
      expect(NAMED.test(bare), `${prop}: ${value}`).toBe(false);
    }
  });
});

/** Every CSS module of the portal (decision 14: the check widened to every module in round 5). */
const MODULES = sources([".module.css"]);

/** Raw lengths in margins, paddings and gaps other than 0 and 1-2 px (borders); tokens and calc of tokens pass. */
function rawSpacing(css: string): string[] {
  const bad: string[] = [];
  for (const m of css.matchAll(/(?:^|[;{\s])((?:margin|padding)(?:-[a-z]+)?|gap|row-gap|column-gap)\s*:\s*([^;}]+)/g)) {
    const value = m[2]!.replace(/var\(--[a-z0-9-]+\)/g, "");
    for (const n of value.matchAll(/(-?\d*\.?\d+)(px|rem|em|%|vh|vw)?/g)) {
      const amount = Number(n[1]);
      const unit = n[2] ?? "";
      if (amount === 0) continue;
      if (unit === "px" && (amount === 1 || amount === 2)) continue;
      bad.push(`${m[1]}: ${m[2]!.trim()}`);
      break;
    }
  }
  return bad;
}

describe("spacing from the scale only (decision 14)", () => {
  it("covers every module, the ones of rounds 1-5 among them", () => {
    expect(MODULES.length).toBeGreaterThanOrEqual(20);
    for (const path of ["components/ui/layout.module.css", "components/reports/reports.module.css", "components/auth/auth.module.css"]) {
      expect(MODULES).toContain(path);
    }
  });

  it.each(MODULES)("%s has no raw margin, padding or gap", (path) => {
    expect(rawSpacing(readFileSync(join(SRC, path), "utf-8"))).toEqual([]);
  });

  it("the check catches a raw value and lets tokens, 0 and 1-2 px through", () => {
    expect(rawSpacing(".a { padding: 10px var(--s2); }")).toEqual(["padding: 10px var(--s2)"]);
    expect(rawSpacing(".a { gap: 6px; }")).toEqual(["gap: 6px"]);
    expect(rawSpacing(".a { margin: 0 auto var(--s3); padding: 1px var(--s2); gap: 2px; }")).toEqual([]);
    expect(rawSpacing(".a { padding: calc(var(--s7) + var(--s4)); }")).toEqual([]);
  });

  it("one control height: the .control class is var(--control-h)", () => {
    const css = readFileSync(join(SRC, "components/ui/controls.module.css"), "utf-8");
    expect(css).toMatch(/\.control\s*\{\s*height:\s*var\(--control-h\);/);
    expect(css).toMatch(/\.sm\s*\{\s*height:\s*30px;/);
  });
});

describe("no deprecated alias is left (decision 11, round 5)", () => {
  it("the check finds an alias and lets the new names through", () => {
    expect(aliasUses("a { color: var(--ink-muted); border: 1px solid var(--line); outline: var(--focus, #000) }")).toEqual([
      "var(--ink-muted",
      "var(--line",
      "var(--focus",
    ]);
    expect(aliasUses("a { color: var(--text-3); padding: var(--s3); font-size: var(--t-sm); box-shadow: var(--shadow-1) }")).toEqual([]);
  });

  it.each(sources([".css", ".tsx", ".ts"]).filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx")))(
    "%s uses no removed alias",
    (path) => {
      expect(aliasUses(readFileSync(join(SRC, path), "utf-8"))).toEqual([]);
    },
  );
});
