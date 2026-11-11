import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { componentSources, type Source } from "@/test/sourceScan";

/** The `.tsx` sources of `src/app` (pages and layouts), as `app/...` paths. */
function appSources(): Source[] {
  const root = join(process.cwd(), "src");
  const out: Source[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) {
        out.push({ path: relative(root, full).split("\\").join("/"), text: readFileSync(full, "utf-8") });
      }
    }
  };
  walk(join(root, "app"));
  return out;
}

/*
 * The confirmation guard (design portal-motion, decision 2; Tests 2): a confirmation of an action just done on a shell
 * page is the toast, never an inline green notice. The entries below stay inline, each for its reason; a new one is
 * a deviation written in its design.
 */
const ALLOW: readonly (readonly [string, string, string])[] = [
  [
    "admin/UserDetail.tsx",
    "T.users.passwordSet",
    "the Reset Password dialog stays open to show it, and a toast behind a focus-trapped dialog cannot be reached by keyboard",
  ],
  ["auth/SignInForms.tsx", "T.auth.passwordChanged", "the sign-in pages have no shell and no toast host"],
  ["auth/SignInForms.tsx", "T.auth.resent", "the sign-in pages have no shell and no toast host"],
  [
    "data/AutomaticCollection.tsx",
    "{message}",
    "Start Collecting's dialog stays open after Start to show what was queued beside the dates (portal-motion, deviation 1)",
  ],
];

const SUCCESS_NOTICE = /<Notice\b[^>]*\btone=(?:"success"|\{\s*"success"\s*\})/;

describe("confirmations are toasts (design portal-motion, decision 2)", () => {
  const sources = [...componentSources(), ...appSources()];

  it("no Notice has tone success outside the allow-list", () => {
    const found: string[] = [];
    for (const src of sources) {
      src.text.split("\n").forEach((line, i) => {
        if (!SUCCESS_NOTICE.test(line)) return;
        if (ALLOW.some(([path, pattern]) => path === src.path && line.includes(pattern))) return;
        found.push(`${src.path}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(found, `a confirmation shown inline; use useToast() (design portal-motion, decision 2):\n${found.join("\n")}`).toEqual([]);
  });

  it("every allow-list entry still covers a line, with its reason", () => {
    const stale = ALLOW.filter(
      ([path, pattern]) =>
        !sources.some((src) => src.path === path && src.text.split("\n").some((l) => SUCCESS_NOTICE.test(l) && l.includes(pattern))),
    );
    expect(stale.map(([p, pat]) => `${p} ${pat}`)).toEqual([]);
    for (const [, , reason] of ALLOW) expect(reason.length).toBeGreaterThan(10);
  });

  it("FlashNotice is defined and imported nowhere", () => {
    const users = sources.filter((src) => /\bFlashNotice\b/.test(src.text)).map((src) => src.path);
    expect(users).toEqual([]);
  });
});
