import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/*
 * The layout signature (design portal-navy-cream, decision 14): for every CSS module and for globals.css, each selector
 * with its declarations normalised so that only what sizes or places a box is left. Colour-only declarations are
 * dropped, every colour value inside another declaration becomes `<c>`, custom properties are dropped and a rule left
 * empty disappears. A recolour therefore leaves the signature unchanged, while any change of padding, margin, size,
 * gap, radius, font weight, position, transition or animation changes it.
 *
 * The snapshot `layout-signature.json` was generated once from main's CSS, in the first commit of the navy-and-cream
 * row, before any colour changed. A row that changes layout on purpose regenerates it with
 * `UPDATE_LAYOUT_SIGNATURE=1 npx vitest run src/components/ui/layoutSignature.test.ts` and says so in its design.
 */

const SRC = join(process.cwd(), "src");
const SNAPSHOT = join(SRC, "components", "ui", "layout-signature.json");

/** Properties that only paint and never size or place a box. */
const PAINT_ONLY = new Set([
  "color",
  "background-color",
  "background-image",
  "border-color",
  "outline-color",
  "box-shadow",
  "fill",
  "stroke",
  "accent-color",
  "caret-color",
  "text-decoration-color",
]);

function paintOnly(prop: string): boolean {
  return PAINT_ONLY.has(prop) || /^border-[a-z-]+-color$/.test(prop);
}

/** The colour tokens of globals.css `:root`, old and new names alike, and the side menu's local set. */
const COLOUR_TOKEN =
  /^--(bg|surface(-2)?|field|border(-strong)?|text(-[23])?|heading|slate-soft|accent(-[a-z]+)?|action(-[a-z]+)?|on-[a-z]+|link(-[a-z]+)?|mark(-[a-z]+)?|focus-[a-z]+|red(-[a-z]+)?|amber(-[a-z]+)?|ochre(-[a-z]+)?|green(-[a-z]+)?|slate(-[a-z]+)?|panel-[a-z-]+|gold(-[a-z]+)?|scrim|nav-[a-z-]+|shadow-[a-z0-9]+)$/;

const NAMED_COLOUR = /\b(transparent|currentcolor|white|black)\b/gi;

/** The index just after the parenthesis that closes the one opening at `open`. */
function closeParen(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i += 1) {
    if (text[i] === "(") depth += 1;
    else if (text[i] === ")") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  return text.length;
}

/** Replace every colour in a value with `<c>`: colour-token `var()`s, hexes, colour functions, gradients, names. */
export function maskColours(value: string): string {
  let out = "";
  let i = 0;
  while (i < value.length) {
    const rest = value.slice(i);
    const fn = /^(var|rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|(?:repeating-)?(?:linear|radial|conic)-gradient)\(/i.exec(rest);
    if (fn && (i === 0 || !/[a-z0-9-]/i.test(value[i - 1]!))) {
      const end = closeParen(value, i + fn[1]!.length);
      const call = value.slice(i, end);
      if (fn[1]!.toLowerCase() === "var") {
        const name = /^var\(\s*(--[a-z0-9-]+)/i.exec(call)?.[1] ?? "";
        out += COLOUR_TOKEN.test(name) ? "<c>" : call;
      } else out += "<c>";
      i = end;
      continue;
    }
    const hex = /^#[0-9a-f]{3,8}\b/i.exec(rest);
    if (hex) {
      out += "<c>";
      i += hex[0].length;
      continue;
    }
    out += value[i];
    i += 1;
  }
  out = out.replace(NAMED_COLOUR, "<c>");
  // a background layered from several colours or gradients is still one painted ground
  return out.replace(/<c>(?:\s*,\s*<c>)+/g, "<c>");
}

/** One declaration as it enters the signature, or null when it only paints or is a custom property. */
export function normaliseDeclaration(prop: string, value: string): string | null {
  const p = prop.trim().toLowerCase();
  if (p.startsWith("--") || paintOnly(p)) return null;
  const v = maskColours(value.trim().replace(/\s+/g, " "));
  return `${p}: ${v}`;
}

type Entry = string;

/** Split a block body into its top-level pieces: declarations and nested blocks. */
function parseBlock(text: string, context: string[], out: Entry[]): string[] {
  const decls: string[] = [];
  let i = 0;
  let start = 0;
  let paren = 0;
  let quote = "";
  while (i < text.length) {
    const ch = text[i]!;
    if (quote) {
      if (ch === "\\") i += 1;
      else if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(") paren += 1;
    else if (ch === ")") paren -= 1;
    else if (paren === 0 && ch === ";") {
      const piece = text.slice(start, i).trim();
      if (piece) {
        const colon = piece.indexOf(":");
        if (piece.startsWith("@")) decls.push(piece.replace(/\s+/g, " "));
        else if (colon > 0) {
          const d = normaliseDeclaration(piece.slice(0, colon), piece.slice(colon + 1));
          if (d) decls.push(d);
        }
      }
      start = i + 1;
    } else if (paren === 0 && ch === "{") {
      const prelude = text.slice(start, i).trim().replace(/\s+/g, " ");
      let depth = 1;
      let j = i + 1;
      let q = "";
      for (; j < text.length && depth > 0; j += 1) {
        const c = text[j]!;
        if (q) {
          if (c === "\\") j += 1;
          else if (c === q) q = "";
        } else if (c === '"' || c === "'") q = c;
        else if (c === "{") depth += 1;
        else if (c === "}") depth -= 1;
      }
      const body = text.slice(i + 1, j - 1);
      if (prelude.startsWith("@")) parseBlock(body, [...context, prelude], out);
      else {
        const inner = parseBlock(body, [...context, prelude], out);
        if (inner.length) out.push(`${[...context, prelude].join(" » ")} { ${inner.join("; ")} }`);
      }
      i = j;
      start = j;
      continue;
    }
    i += 1;
  }
  const tail = text.slice(start).trim();
  if (tail && !tail.startsWith("@")) {
    const colon = tail.indexOf(":");
    if (colon > 0) {
      const d = normaliseDeclaration(tail.slice(0, colon), tail.slice(colon + 1));
      if (d) decls.push(d);
    }
  }
  return decls;
}

/** The signature of one stylesheet: its rules in source order, each with its layout declarations. */
export function signature(css: string): Entry[] {
  const out: Entry[] = [];
  parseBlock(css.replace(/\/\*[\s\S]*?\*\//g, ""), [], out);
  return out;
}

/**
 * Rules are emitted when their block closes, so a nested rule comes before its parent. The order inside one file is
 * stable for the same source, which is all the comparison needs.
 */
function stylesheets(dir = SRC): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...stylesheets(path));
    else if (name.endsWith(".module.css") || (name === "globals.css" && dir.endsWith("app"))) out.push(path);
  }
  return out;
}

function current(): Record<string, Entry[]> {
  const out: Record<string, Entry[]> = {};
  for (const path of stylesheets().sort()) {
    out[relative(SRC, path).split("\\").join("/")] = signature(readFileSync(path, "utf-8"));
  }
  return out;
}

describe("the layout signature (design portal-navy-cream, decision 14)", () => {
  it("normalises declarations: keeps sizes and places, drops paint, masks colours", () => {
    const css = `
      .a { padding: 10px; font-weight: 600; border: 2px solid var(--accent); transform: translateY(-1px);
           color: var(--accent); box-shadow: 0 0 0 4px var(--accent-ring); --nav-bg: #000; }
      .b { border: 1px solid var(--accent); }
      .c { border: 1px solid #fff; }
      .d { color: red; background-color: #fff; }
      .e { background: radial-gradient(1px 1px at 0 0, rgba(0,0,0,.3), transparent 60%), linear-gradient(160deg, var(--panel-from), var(--panel-to)); }
      .f { margin: var(--s2) 0; }
    `;
    expect(signature(css)).toEqual([
      ".a { padding: 10px; font-weight: 600; border: 2px solid <c>; transform: translateY(-1px) }",
      ".b { border: 1px solid <c> }",
      ".c { border: 1px solid <c> }",
      ".e { background: <c> }",
      ".f { margin: var(--s2) 0 }",
    ]);
  });

  it("a changed width or weight changes the signature; a changed colour does not", () => {
    const before = signature(".a { border: 1px solid var(--accent); font-weight: 600; color: var(--accent) }");
    expect(signature(".a { border: 1px solid var(--action); font-weight: 600; color: var(--link) }")).toEqual(before);
    expect(signature(".a { border: 2px solid var(--accent); font-weight: 600 }")).not.toEqual(before);
    expect(signature(".a { border: 1px solid var(--accent); font-weight: 700 }")).not.toEqual(before);
  });

  it("masks the gold tokens as colours (design signin-gold-emblem, decision 13)", () => {
    expect(signature(".g { background: var(--gold); background-size: 240% 100%; border-left: 1px solid var(--gold-line) }")).toEqual([
      ".g { background: <c>; background-size: 240% 100%; border-left: 1px solid <c> }",
    ]);
    expect(signature(".g { background: var(--gold-deep) }")).toEqual(signature(".g { background: var(--gold-light) }"));
  });

  it("follows at-rules and keeps keyframes", () => {
    const css = "@media (max-width: 819px) { .a { padding: var(--s2); color: #000 } } @keyframes k { from { opacity: 0 } }";
    expect(signature(css)).toEqual(["@media (max-width: 819px) » .a { padding: var(--s2) }", "@keyframes k » from { opacity: 0 }"]);
  });

  it("follows @container blocks as it follows @media (design control-spacing-sweep, decision 16)", () => {
    const css = ".g { container-type: inline-size; container-name: fc-fields } @container fc-fields (min-width: 412px) { .g > [data-wide] { grid-column: span 2; color: red } }";
    expect(signature(css)).toEqual([
      ".g { container-type: inline-size; container-name: fc-fields }",
      "@container fc-fields (min-width: 412px) » .g > [data-wide] { grid-column: span 2 }",
    ]);
  });

  it("equals main's", () => {
    const now = current();
    if (process.env.UPDATE_LAYOUT_SIGNATURE === "1" || !existsSync(SNAPSHOT)) {
      writeFileSync(SNAPSHOT, `${JSON.stringify(now, null, 2)}\n`, "utf-8");
    }
    const saved = JSON.parse(readFileSync(SNAPSHOT, "utf-8")) as Record<string, Entry[]>;
    expect(Object.keys(now).sort()).toEqual(Object.keys(saved).sort());
    for (const file of Object.keys(saved)) expect(now[file], file).toEqual(saved[file]);
  });
});
