import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/*
 * The motion rules of design portal-motion (decisions 7, 8, 9 and 12; Tests 5), read from the CSS sources: the new
 * transitions stay on the motion tokens, the menu slide is a transform on pointer devices only, the two layers are out
 * of the flow, and the reduced-motion block is unchanged.
 */

const SRC = join(process.cwd(), "src");
const read = (path: string) => readFileSync(join(SRC, path), "utf-8");

interface Rule {
  /** The enclosing at-rules, outermost first (`@media (hover: hover) and (pointer: fine)`). */
  context: string[];
  selector: string;
  decls: Record<string, string>;
}

/** Every rule of a stylesheet with its declarations and enclosing at-rules (comments removed). */
function rules(css: string): Rule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Rule[] = [];
  const walk = (body: string, context: string[]) => {
    let i = 0;
    let start = 0;
    while (i < body.length) {
      if (body[i] === "{") {
        const prelude = body.slice(start, i).trim().replace(/\s+/g, " ");
        let depth = 1;
        let j = i + 1;
        for (; j < body.length && depth > 0; j += 1) {
          if (body[j] === "{") depth += 1;
          else if (body[j] === "}") depth -= 1;
        }
        const inner = body.slice(i + 1, j - 1);
        if (prelude.startsWith("@")) walk(inner, [...context, prelude]);
        else {
          const decls: Record<string, string> = {};
          for (const piece of inner.split(";")) {
            const colon = piece.indexOf(":");
            if (colon > 0) decls[piece.slice(0, colon).trim()] = piece.slice(colon + 1).trim().replace(/\s+/g, " ");
          }
          out.push({ context, selector: prelude, decls });
        }
        i = j;
        start = j;
        continue;
      }
      if (body[i] === ";") start = i + 1;
      i += 1;
    }
  };
  walk(text, []);
  return out;
}

const feedback = rules(read("components/ui/feedback.module.css"));
const controls = rules(read("components/ui/controls.module.css"));
const shell = rules(read("components/shell/shell.module.css"));

function find(list: Rule[], selector: string): Rule[] {
  const found = list.filter((r) => r.selector === selector);
  if (found.length === 0) throw new Error(`no rule ${selector}`);
  return found;
}

/** The items of a `transition` list, split at top-level commas. */
function items(value: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < value.length; i += 1) {
    if (value[i] === "(") depth += 1;
    else if (value[i] === ")") depth -= 1;
    else if (value[i] === "," && depth === 0) {
      out.push(value.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(value.slice(start).trim());
  return out;
}

const ON_TOKENS = /^[a-z-]+ var\(--(fast|med|slow)\) var\(--ease\)$/;
// the visibility switch of a closing layer: at once, or after --med (the side menu's children do the same)
const VISIBILITY_SWITCH = /^visibility 0s linear (0s|var\(--med\))$/;

describe("the motion rules (design portal-motion, Tests 5)", () => {
  it("the new transitions name only the duration tokens with var(--ease)", () => {
    const transitions = [
      ...find(controls, ".thumb"),
      ...find(feedback, ".toast"),
      ...find(feedback, ".toast[data-open]"),
      ...find(feedback, ".toast[data-closing]"),
      ...find(shell, ".navIcon, .navLabel"),
    ].map((r) => [r.selector, r.decls.transition] as const);
    for (const [selector, value] of transitions) {
      expect(value, selector).toBeTruthy();
      for (const item of items(value!)) {
        const ok = ON_TOKENS.test(item) || VISIBILITY_SWITCH.test(item);
        expect(ok, `${selector}: ${item}`).toBe(true);
      }
    }
  });

  it("the menu hover slide is a transform on pointer devices, never on the current item", () => {
    const hover = shell.filter((r) => r.selector.includes(":hover") && (r.selector.includes(".navIcon") || r.selector.includes(".navLabel")));
    expect(hover).toHaveLength(1);
    const rule = hover[0]!;
    expect(rule.context).toEqual(["@media (hover: hover) and (pointer: fine)"]);
    for (const part of rule.selector.split(",")) expect(part).toContain(':not([aria-current="page"])');
    expect(Object.keys(rule.decls)).toEqual(["transform"]);
    expect(rule.decls.transform).toBe("translateX(var(--s1))");
    for (const banned of ["padding", "padding-left", "margin", "margin-left", "width", "left"]) {
      expect(rule.decls[banned]).toBeUndefined();
    }
  });

  it("the thumb and the toast host are out of the flow", () => {
    expect(find(controls, ".thumb")[0]!.decls.position).toBe("absolute");
    expect(find(feedback, ".toastHost")[0]!.decls.position).toBe("fixed");
    expect(find(feedback, ".toastHost")[0]!.decls["z-index"]).toBe("70");
    expect(find(feedback, ".toastHost")[0]!.decls["pointer-events"]).toBe("none");
    expect(find(feedback, ".toast")[0]!.decls["pointer-events"]).toBe("auto");
  });

  it("the reduced-motion block is unchanged (but for the emblem's --turn and --sweep, design signin-gold-emblem)", () => {
    const globals = read("app/globals.css");
    expect(globals).toContain(`@media (prefers-reduced-motion: reduce) {
  :root {
    --fast: 0ms;
    --med: 0ms;
    --slow: 0ms;
    --turn: 0ms;
    --sweep: 0ms;
  }

  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }
}`);
  });
});
