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

/** The navy-and-cream retirements (design portal-navy-cream, decisions 1 and 6): the blue accent split into navy and
 * orange, amber replaced by ochre. */
const RETIRED_NAVY_CREAM = ["--accent", "--accent-hover", "--accent-soft", "--accent-ring", "--amber", "--amber-soft"];

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
function aliasUses(text: string, retired: string[] = [...REMOVED_ALIASES, ...RETIRED_NAVY_CREAM]): string[] {
  const names = retired.map((a) => a.slice(2)).join("|");
  return [...text.matchAll(new RegExp(`var\\(--(${names})(?=[,)\\s])`, "g"))].map((m) => m[0]);
}

describe("design tokens (design portal-ui-redesign, decision 11)", () => {
  it("carry the v4 values (spacing, type, motion and sizes)", () => {
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
    // design portal-ui-kit-fixes, decision 7: the card row's label column, beside the other fixed columns
    expect(TOKENS["--card-label-w"]).toBe("112px");
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
});

/** Every colour token of the navy-and-cream palette (design portal-navy-cream, decision 1). */
const NAVY_CREAM: Record<string, string> = {
  "--bg": "#f7f1e3",
  "--surface": "#fffbf2",
  "--surface-2": "#f6edda",
  "--field": "#ffffff",
  "--border": "#e2d6be",
  "--border-strong": "#cdbfa6",
  "--text": "#13213f",
  "--text-2": "#4a5570",
  "--text-3": "#5b6580",
  "--heading": "#0f1e3d",
  "--slate-soft": "#efe6d2",
  "--action": "#22386a",
  "--action-hover": "#2e4785",
  "--action-soft": "#e3e8f2",
  "--on-action": "#ffffff",
  "--link": "#3c5a94",
  "--link-hover": "var(--action)",
  "--mark": "#f28c28",
  "--mark-hover": "#f59a3e",
  "--on-mark": "#0f1e3d",
  "--mark-text": "#b4470c",
  "--mark-soft": "#fde9d1",
  "--mark-line": "#f3c99b",
  "--mark-glow": "rgba(242, 140, 40, 0.45)",
  "--focus-line": "var(--mark-text)",
  "--focus-ring": "rgba(242, 140, 40, 0.35)",
  "--red": "#b42318",
  "--red-text": "#b42318",
  "--red-soft": "#fbe7e4",
  "--on-red": "#ffffff",
  "--red-line": "#ebb1a9",
  "--ochre": "#7a5a00",
  "--ochre-soft": "#f5eccb",
  "--ochre-line": "#e3d08f",
  "--green": "#0b6b3a",
  "--green-soft": "#e2f0e5",
  "--green-line": "#a9d3b5",
  "--panel-from": "#0f1e3d",
  "--panel-to": "#0b1730",
  "--panel-text": "#c9d3e6",
  "--panel-strong": "#ffffff",
  "--panel-muted": "#8c97b0",
  "--panel-accent": "#f6c48e",
  "--panel-raised": "#22386a",
  "--panel-hover": "#1c2b4d",
  "--panel-line": "#2a3b5e",
  "--panel-dots": "rgba(255, 255, 255, 0.06)",
  "--panel-tile": "rgba(255, 255, 255, 0.03)",
  "--panel-tile-line": "rgba(255, 255, 255, 0.1)",
  "--scrim": "rgba(15, 30, 61, 0.4)",
  "--shadow-1": "0 1px 2px rgba(15, 30, 61, 0.06)",
  "--shadow-2": "0 4px 12px rgba(15, 30, 61, 0.08)",
  "--shadow-3": "0 16px 40px rgba(15, 30, 61, 0.16)",
  "--shadow-knob": "0 1px 2px rgba(15, 30, 61, 0.2)",
};

describe("the navy and cream palette (design portal-navy-cream, decisions 1, 4 and 5)", () => {
  it("carry the navy and cream values", () => {
    for (const [name, value] of Object.entries(NAVY_CREAM)) expect(TOKENS[name], name).toBe(value);
  });

  it("the navy and cream retirements: the blue accent and amber are gone from :root", () => {
    for (const name of RETIRED_NAVY_CREAM) expect(TOKENS[name], name).toBeUndefined();
  });

  // every text and background pair meets WCAG 2.1 AA (4.5:1)
  it.each([
    ...["--bg", "--surface", "--surface-2", "--field", "--slate-soft", "--action-soft", "--ochre-soft", "--green-soft"].map(
      (bg) => ["--text", bg],
    ),
    ...["--bg", "--surface", "--surface-2", "--field", "--slate-soft", "--mark-soft", "--action-soft"].map((bg) => ["--text-2", bg]),
    ...["--bg", "--surface", "--surface-2", "--slate-soft", "--field", "--ochre-soft", "--mark-soft", "--action-soft"].map(
      (bg) => ["--text-3", bg],
    ),
    ...["--bg", "--surface", "--action-soft", "--mark-soft"].map((bg) => ["--heading", bg]),
    ...["--surface", "--bg", "--slate-soft", "--action-soft", "--field", "--surface-2"].map((bg) => ["--action", bg]),
    ...["--surface", "--bg", "--surface-2", "--action-soft"].map((bg) => ["--link", bg]),
    ["--on-action", "--action"],
    ["--on-action", "--action-hover"],
    ["--on-mark", "--mark"],
    ["--on-mark", "--mark-hover"],
    ...["--surface", "--bg", "--mark-soft", "--surface-2", "--field"].map((bg) => ["--mark-text", bg]),
    ["--on-red", "--red"],
    ...["--red-soft", "--surface", "--bg", "--surface-2", "--slate-soft"].map((bg) => ["--red-text", bg]),
    ...["--ochre-soft", "--slate-soft", "--surface", "--surface-2", "--mark-soft"].map((bg) => ["--ochre", bg]),
    ...["--green-soft", "--surface", "--slate-soft"].map((bg) => ["--green", bg]),
    // design dashboard-my-work-polish, decision 14: a badge's tone as a fill (`look="solid"`)
    ["--surface", "--text-2"],
    ["--surface", "--red-text"],
    ["--surface", "--ochre"],
    ["--surface", "--green"],
    // the navy ground: the public pages' panel, the side menu and the Save bar
    ...["--panel-from", "--panel-to", "--panel-raised", "--panel-hover"].map((bg) => ["--panel-text", bg]),
    ...["--panel-from", "--panel-raised", "--panel-hover"].map((bg) => ["--panel-strong", bg]),
    ...["--panel-from", "--panel-to", "--panel-hover"].map((bg) => ["--panel-muted", bg]),
    ...["--panel-from", "--panel-to"].map((bg) => ["--panel-accent", bg]),
  ])("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(hex(fg!), hex(bg!))).toBeGreaterThanOrEqual(4.5);
  });

  // WCAG 1.4.11 (decision 5): a mark that shows a state on its own is at least 3:1 against what it sits on
  it.each([
    ...["--bg", "--surface", "--surface-2", "--field"].map((bg) => ["--focus-line", bg]),
    // the side menu's current bar and focus ring on navy
    ["--mark", "--panel-from"],
    // a count on the current menu item
    ["--mark", "--panel-raised"],
  ])("the stand-alone mark %s on %s is at least 3:1", (fg, bg) => {
    expect(contrast(hex(fg!), hex(bg!))).toBeGreaterThanOrEqual(3);
  });

  it("white on orange fails, which is why an orange fill always carries navy text (decision 4)", () => {
    expect(contrast("#ffffff", hex("--mark"))).toBeLessThan(4.5);
    expect(contrast(hex("--on-mark"), hex("--mark"))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("the next hearing badge's colours (design next-hearing-highlight, decisions 4, 5 and 13)", () => {
  it("defines --on-red, the text on a solid red fill", () => {
    expect(TOKENS["--on-red"]).toBe("#ffffff");
  });

  it.each([
    // strong, soft (ochre since portal-navy-cream, decision 6), warning (Date Passed), muted (No Date Yet, Disposed)
    // on the surface and the zebra row
    ["--on-red", "--red"],
    ["--ochre", "--ochre-soft"],
    ["--ochre", "--slate-soft"],
    ["--text-3", "--surface"],
    ["--text-3", "--surface-2"],
    ["--text", "--surface"],
    ["--text-2", "--surface"],
    // a suggested date's outline on the surface
    ["--red-text", "--surface"],
    ["--ochre", "--surface"],
  ])("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(hex(fg), hex(bg))).toBeGreaterThanOrEqual(4.5);
  });
});

/** Every CSS module, for the colour guards (they run before the spacing block below defines MODULES). */
const MODULES_FOR_COLOUR = sources([".module.css"]);

/** A stylesheet without its comments. */
function uncommented(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** globals.css outside its token blocks (`:root { ... }`, the base one and the reduced-motion one). */
function globalsOutsideRoot(): string {
  return uncommented(globals).replace(/:root\s*\{[^}]*\}/g, "");
}

const COLOUR_FUNCTION = /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i;
const HEX = /#[0-9a-f]{3,8}\b/i;
const NAMED_COLOUR = /\b(white|black|red|green|blue|amber|orange|yellow|grey|gray|silver|navy|maroon|purple|cream|ivory|beige)\b/i;
const COLOUR_PROPERTY =
  /(?:^|[;{\s])(color|background(?:-color)?|border(?:-[a-z]+)?(?:-color)?|outline(?:-color)?|fill|stroke|box-shadow|accent-color|caret-color|text-decoration-color)\s*:\s*([^;}]+)/g;

/** The colour literals of a stylesheet: hexes, colour functions, and named colours in colour properties. */
export function colourLiterals(css: string): string[] {
  const text = uncommented(css);
  const found: string[] = [];
  for (const m of text.matchAll(new RegExp(HEX.source, "gi"))) found.push(m[0]);
  for (const m of text.matchAll(new RegExp(COLOUR_FUNCTION.source, "gi"))) found.push(m[0]);
  for (const [, prop, value] of text.matchAll(COLOUR_PROPERTY)) {
    const bare = value!.replace(/var\(--[a-z0-9-]+\)/g, "");
    const named = NAMED_COLOUR.exec(bare);
    if (named) found.push(`${prop}: ${named[0]}`);
  }
  return found;
}

describe("no colour literal outside the tokens (design portal-navy-cream, decisions 7 and 14)", () => {
  it("the check finds hexes, colour functions and named colours, and lets tokens and keywords through", () => {
    expect(colourLiterals(".a { color: #fff; background: rgba(0, 0, 0, 0.2); border-color: white; }")).toEqual([
      "#fff",
      "rgba(",
      "border-color: white",
    ]);
    expect(
      colourLiterals(
        ".a { color: var(--text); background: transparent; border: 1px solid currentColor; fill: inherit; white-space: nowrap }",
      ),
    ).toEqual([]);
  });

  it.each(MODULES_FOR_COLOUR)("%s names no colour literal", (path) => {
    expect(colourLiterals(readFileSync(join(SRC, path), "utf-8"))).toEqual([]);
  });

  it("globals.css names no colour literal outside :root", () => {
    expect(colourLiterals(globalsOutsideRoot())).toEqual([]);
  });

  it.each(sources([".tsx", ".ts"]).filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx") && !p.endsWith(".d.ts")))(
    "%s has no hex colour",
    (path) => {
      const text = readFileSync(join(SRC, path), "utf-8");
      // a hex in a string or an attribute: "#fff", '#1d4ed8', {"#8892a0"}
      expect(text.match(/["'`]#[0-9a-f]{3,8}["'`]/gi) ?? []).toEqual([]);
    },
  );
});

/** Every rule of a stylesheet as [selector, body] (nested at-rules flattened; good enough for these guards). */
function rules(css: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const m of uncommented(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) out.push([m[1]!.trim(), m[2]!]);
  return out;
}

/** Rules that put an orange fill behind text other than navy, or that write words in bright orange (decision 4). */
export function orangeBreaches(css: string): string[] {
  const bad: string[] = [];
  for (const [selector, body] of rules(css)) {
    const orangeFill = /(?:^|;|\s)background(?:-color)?\s*:\s*var\(--mark(?:-hover)?\)/.test(body);
    if (orangeFill && !/(?:^|;|\s)color\s*:\s*var\(--on-mark\)/.test(body)) bad.push(`${selector}: orange fill without --on-mark`);
    if (/(?:^|;|\s)color\s*:\s*var\(--mark(?:-hover)?\)/.test(body)) bad.push(`${selector}: bright orange words`);
  }
  return bad;
}

const STYLESHEETS = ["app/globals.css", ...MODULES_FOR_COLOUR];

describe("orange fills carry navy text (design portal-navy-cream, decision 4)", () => {
  it("the check catches white on orange and bright orange words, and lets navy on orange through", () => {
    expect(orangeBreaches(".a { background: var(--mark); color: #fff; }")).toEqual([".a: orange fill without --on-mark"]);
    expect(orangeBreaches(".b { background: var(--mark-hover); }")).toEqual([".b: orange fill without --on-mark"]);
    expect(orangeBreaches(".c { color: var(--mark); }")).toEqual([".c: bright orange words"]);
    expect(orangeBreaches(".d { background: var(--mark); color: var(--on-mark); } .e { color: var(--mark-text); }")).toEqual([]);
  });

  it.each(STYLESHEETS)("%s keeps the orange rules", (path) => {
    expect(orangeBreaches(readFileSync(join(SRC, path), "utf-8"))).toEqual([]);
  });
});

/** The `--nav-*` set of the first `.sidebar { ... }` rule in a piece of CSS, resolved to the root tokens. */
function navSet(css: string): Record<string, string> {
  const m = /\.sidebar\s*\{([^}]*)\}/.exec(css);
  const out: Record<string, string> = {};
  for (const d of (m?.[1] ?? "").matchAll(/(--nav-[a-z-]+):\s*var\((--[a-z0-9-]+)\)/g)) out[d[1]!] = d[2]!;
  return out;
}

describe("the side menu's two colour sets (design portal-navy-cream, decision 9)", () => {
  const shell = uncommented(readFileSync(join(SRC, "components/shell/shell.module.css"), "utf-8"));
  const phone = shell.slice(shell.indexOf("@media (max-width: 819px)"));
  const sets: Array<[string, Record<string, string>]> = [
    ["navy (laptops and tablets)", navSet(shell)],
    ["cream (the phone drawer)", navSet(phone)],
  ];

  it("both sets define every colour the menu reads", () => {
    const names = ["bg", "text", "strong", "muted", "hover", "current-bg", "current-text", "line", "mark", "focus"].map((n) => `--nav-${n}`);
    for (const [, set] of sets) expect(Object.keys(set).sort()).toEqual([...names].sort());
    expect(sets[0]![1]["--nav-bg"]).toBe("--panel-from");
    // deep orange on navy is only 3.02:1, so on navy the current bar and the focus ring are bright orange
    expect(sets[0]![1]["--nav-focus"]).toBe("--mark");
    expect(sets[0]![1]["--nav-mark"]).toBe("--mark");
    expect(sets[1]![1]["--nav-bg"]).toBe("--surface");
  });

  it.each(sets)("the %s set meets AA for text and 3:1 for marks", (_, set) => {
    const c = (fg: string, bg: string) => contrast(hex(set[fg]!), hex(set[bg]!));
    expect(c("--nav-text", "--nav-bg")).toBeGreaterThanOrEqual(4.5);
    expect(c("--nav-strong", "--nav-hover")).toBeGreaterThanOrEqual(4.5);
    expect(c("--nav-current-text", "--nav-current-bg")).toBeGreaterThanOrEqual(4.5);
    expect(c("--nav-muted", "--nav-bg")).toBeGreaterThanOrEqual(4.5);
    expect(c("--nav-mark", "--nav-bg")).toBeGreaterThanOrEqual(3);
    expect(c("--nav-focus", "--nav-bg")).toBeGreaterThanOrEqual(3);
  });

  it("the menu's rules read only the local set", () => {
    const menu = ["groupLabel", "onPath", "chevron", "foot"].map((cls) => {
      const m = new RegExp(`\\.${cls}\\s*\\{([^}]*)\\}`).exec(shell);
      return m?.[1] ?? "";
    });
    for (const body of menu) {
      for (const v of body.matchAll(/var\((--[a-z0-9-]+)\)/g)) {
        if (/^--(s\d|t-|r-|med|fast|slow|ease|icon-w)/.test(v[1]!)) continue;
        expect(v[1]!.startsWith("--nav-"), v[1]).toBe(true);
      }
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

describe("no deprecated alias is left (decision 11, round 5; portal-navy-cream, decision 1)", () => {
  it("the check finds an alias and lets the new names through", () => {
    expect(aliasUses("a { color: var(--ink-muted); border: 1px solid var(--line); outline: var(--focus, #000) }")).toEqual([
      "var(--ink-muted",
      "var(--line",
      "var(--focus",
    ]);
    expect(aliasUses("a { color: var(--text-3); padding: var(--s3); font-size: var(--t-sm); box-shadow: var(--shadow-1) }")).toEqual([]);
    // the navy-and-cream retirements, while the panel's own accent and the CSS property accent-color pass
    expect(aliasUses("a { color: var(--accent); background: var(--amber-soft); border-color: var(--accent-hover) }")).toEqual([
      "var(--accent",
      "var(--amber-soft",
      "var(--accent-hover",
    ]);
    expect(aliasUses("a { color: var(--panel-accent); accent-color: var(--action); background: var(--ochre-soft) }")).toEqual([]);
  });

  it.each(sources([".css", ".tsx", ".ts"]).filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx")))(
    "%s uses no removed alias",
    (path) => {
      expect(aliasUses(readFileSync(join(SRC, path), "utf-8"))).toEqual([]);
    },
  );
});
