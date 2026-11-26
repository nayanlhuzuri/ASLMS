// @vitest-environment node
/**
 * The home page's motion and layout, read statically (design home-page, decisions 9, 11, 12 and 13; design
 * home-page-refinements, decisions 1, 3 and 5): the step change and the arrival fade run on var(--med) with var(--ease)
 * and never on literal milliseconds, no smooth scrolling by CSS, the arrival fade animates opacity only, the bands reach
 * the edges by a painted layer exactly as wide as the page, the hero is one screen tall, the pictures animate only
 * opacity and transform on the motion tokens, and the conversation's thread is the one box that clips, vertically only.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const uncommented = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
const home = uncommented(readFileSync(join(SRC, "components", "home", "home.module.css"), "utf-8"));
const shell = uncommented(readFileSync(join(SRC, "components", "shell", "shell.module.css"), "utf-8"));

/** The declarations of the first rule whose selector is exactly `selector`. */
function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const m = new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  if (!m) throw new Error(`no rule ${selector}`);
  return m[1]!;
}

/** The body of a `@keyframes` block. */
function keyframes(css: string, name: string): string {
  const start = css.indexOf(`@keyframes ${name}`);
  if (start < 0) throw new Error(`no keyframes ${name}`);
  let depth = 0;
  for (let i = css.indexOf("{", start); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}" && --depth === 0) return css.slice(start, i + 1);
  }
  throw new Error(`unclosed keyframes ${name}`);
}

describe("the home page's motion (decisions 12 and 13)", () => {
  it("the step animations use var(--med) and var(--ease)", () => {
    expect(rule(home, '.step[data-phase="enter"]')).toMatch(/animation:\s*step-in-forward var\(--med\) var\(--ease\) both/);
    expect(rule(home, '.step[data-phase="leave"]')).toMatch(/animation:\s*step-out-forward var\(--med\) var\(--ease\) both/);
    for (const name of ["step-in-forward", "step-in-back", "step-out-forward", "step-out-back"]) {
      const body = keyframes(home, name);
      expect(body).toMatch(/opacity/);
      expect(body).toMatch(/translateX\((-)?12px\)/);
    }
  });

  it("the arrival fade uses var(--med) and var(--ease) and animates opacity only", () => {
    expect(rule(shell, ".frame[data-arrive]")).toMatch(/animation:\s*portal-arrive var\(--med\) var\(--ease\) both/);
    const body = keyframes(shell, "portal-arrive");
    const properties = [...body.matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1]);
    expect(new Set(properties)).toEqual(new Set(["opacity"]));
  });

  it("names no literal milliseconds or seconds in an animation or transition", () => {
    for (const css of [home, shell.slice(shell.indexOf(".frame[data-arrive]"), shell.indexOf("@keyframes portal-arrive"))]) {
      expect(css).not.toMatch(/(animation|transition)[^;]*\b\d+(\.\d+)?m?s\b/);
    }
  });

  it("uses no CSS smooth scrolling (decision 11)", () => {
    expect(home).not.toMatch(/scroll-behavior\s*:\s*smooth/);
    expect(shell).not.toMatch(/scroll-behavior\s*:\s*smooth/);
  });
});

describe("the bands and the gutter (decision 9)", () => {
  it("main keeps a gutter of --s4, and the page clips nothing (uicheck's clipped kind)", () => {
    expect(rule(home, ".main")).toMatch(/padding:\s*0 var\(--s4\)/);
    expect(rule(home, ".page")).toMatch(/container-type:\s*inline-size/);
    // the only sideways overflow: hidden is deliberate truncation with an ellipsis (uicheck exempts it)
    for (const m of home.matchAll(/([^{}]+)\{([^}]*overflow(?:-x)?:\s*(?:hidden|clip)[^}]*)\}/g)) {
      expect(m[2], m[1]!.trim()).toMatch(/text-overflow:\s*ellipsis/);
    }
  });

  it("the conversation's thread clips vertically only, so nothing is cut off sideways (refinements, decision 3)", () => {
    const thread = rule(home, ".chatThread");
    expect(thread).toMatch(/overflow-x:\s*visible/);
    expect(thread).toMatch(/overflow-y:\s*clip/);
    expect([...home.matchAll(/overflow-y:\s*(hidden|clip)/g)]).toHaveLength(1);
  });

  it("a band reaches the edges only by its painted layer behind it, exactly the page's width", () => {
    const layer = rule(home, ".band::before");
    expect(layer).toMatch(/position:\s*absolute/);
    expect(layer).toMatch(/inset:\s*0 calc\(50% - 50cqw\)/);
    expect(layer).toMatch(/z-index:\s*-1/);
    expect(rule(home, ".band")).toMatch(/isolation:\s*isolate/);
  });
});

describe("the first screen (refinements, decision 1)", () => {
  it("the hero is exactly one screen tall where it fits: min-height 100svh after the 100vh fallback", () => {
    const hero = rule(home, ".hero");
    expect(hero).toMatch(/min-height:\s*100vh;\s*min-height:\s*100svh/);
    expect(hero).not.toMatch(/(^|;)\s*height:/);
  });

  it("the first screen's link nudges on the motion tokens, so it is still under reduced motion", () => {
    expect(rule(home, ".cueIcon")).toMatch(/animation:\s*cue-nudge calc\(var\(--slow\) \* [\d.]+\) var\(--ease\) infinite/);
  });
});

describe("the pictures' motion (refinements, decision 3)", () => {
  it("every animation of the home page runs on a motion token, so reduced motion stops it", () => {
    for (const m of home.matchAll(/animation:\s*([^;]+);/g)) expect(m[1], m[1]).toMatch(/var\(--(fast|med|slow)\)/);
    for (const m of home.matchAll(/transition:\s*([^;]+);/g)) expect(m[1], m[1]).toMatch(/var\(--(fast|med|slow)\) var\(--ease\)/);
  });

  it("the picture keyframes animate opacity and transform only", () => {
    for (const name of ["chat-rise", "chat-fade", "chat-dot", "chat-caret", "cue-nudge"]) {
      const body = keyframes(home, name);
      const properties = new Set([...body.matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1]));
      for (const p of properties) expect(["opacity", "transform"], `${name}: ${p}`).toContain(p);
    }
  });

  it("from 1024 px the pictures sit side by side, the Case Inbox wider, and the Assistant takes the row's height", () => {
    const wide = home.slice(home.indexOf("@media (min-width: 1024px)"));
    expect(rule(wide, ".shots")).toMatch(/grid-template-columns:\s*minmax\(0, 1\.65fr\) minmax\(0, 1fr\)/);
    expect(rule(wide, ".chatShot")).toMatch(/height:\s*0;\s*min-height:\s*100%/);
  });
});
