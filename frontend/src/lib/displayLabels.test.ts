/**
 * The label helpers (design portal-names-and-labels, decisions 10 and 14) and the source guard that keeps every code
 * fallback in `displayLabels.ts`: a new `MAP[code] ?? code` lookup or `.replace(/_/g, " ")` elsewhere fails, so a code
 * never reaches the screen as a lowercase code.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { labelFor, labelOf, serverLabel } from "./displayLabels";

describe("labelFor", () => {
  it("returns the map's label, Title-Cases an unknown code and gives — for none", () => {
    expect(labelFor({ pending: "Pending" }, "pending")).toBe("Pending");
    expect(labelFor({ pending: "Pending" }, "not_found")).toBe("Not Found");
    expect(labelFor(undefined, "ownership.claim")).toBe("Ownership Claim");
    expect(labelFor(undefined, "cnr_search")).toBe("CNR Search");
    expect(labelFor({}, null)).toBe("—");
    expect(labelFor({}, undefined)).toBe("—");
    expect(labelFor({}, "")).toBe("—");
    // the map is read first: an "" option with a label keeps it (the date presets' "Any")
    expect(labelFor({ "": "Any" }, "")).toBe("Any");
  });
});

describe("serverLabel", () => {
  it("puts server labels in Title Case and leaves a Title Case label unchanged", () => {
    expect(serverLabel("Parawise comments")).toBe("Parawise Comments");
    expect(serverLabel("Other - see remark")).toBe("Other - See Remark");
    expect(serverLabel("Government order / notification")).toBe("Government Order / Notification");
    // "as" is not among the shared rule's small words (design portal-ui-polish-2, decision 2): see the Deviations
    expect(serverLabel("Next date reported as wrong")).toBe("Next Date Reported As Wrong");
    expect(serverLabel("Super Administrator")).toBe("Super Administrator");
    expect(serverLabel("File in Court")).toBe("File in Court");
  });

  it("keeps an empty value empty", () => {
    expect(serverLabel(null)).toBeNull();
    expect(serverLabel(undefined)).toBeUndefined();
    expect(serverLabel("")).toBe("");
  });
});

describe("labelOf", () => {
  const list = [
    { code: "dept_officer", label: "Department officer" },
    { code: "auditor", label: "Auditor" },
  ];
  it("Title-Cases the server list's label and falls back through labelFor", () => {
    expect(labelOf(list, "dept_officer")).toBe("Department Officer");
    expect(labelOf(list, "auditor")).toBe("Auditor");
    expect(labelOf(list, "state_oversight")).toBe("State Oversight");
    expect(labelOf(undefined, "auditor")).toBe("Auditor");
    expect(labelOf(list, null)).toBe("—");
  });
});

// ------------------------------------------------------------------------------------------------ the source guard

const SRC = join(process.cwd(), "src");

function sources(dir: string): { path: string; text: string }[] {
  const out: { path: string; text: string }[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name !== "test") out.push(...sources(full));
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && !name.endsWith(".d.ts")) {
      out.push({ path: relative(SRC, full).replace(/\\/g, "/"), text: readFileSync(full, "utf-8") });
    }
  }
  return out;
}

/** `MAP[expr] ?? expr` (also with `as Type` in the index): a lookup that falls back to the raw code. */
const RAW_FALLBACK = /\[([^[\]]+?)(?: as \w+)?\] \?\? ([\w.?]+)/g;
const UNDERSCORES = /\.replace\(\/_\/g, ?" "\)/;

/** [file, a pattern of the line, the reason]: a code that is meant to show as itself. */
const ALLOW: [string, string, string][] = [
  ["lib/audit.ts", "T.audit.actionNames[code] ?? code", "decision 20: an action code with no name shows the code itself, never an invented name"],
  ["lib/audit.ts", "groupLabels[key] ?? key", "decision 20: an action prefix with no group label shows the prefix itself"],
  ["components/causelist/OwnershipCell.tsx", "names[owner] ?? owner", "decision 5: an office without a known name shows its code"],
];

function findings(): string[] {
  const out: string[] = [];
  for (const { path, text } of sources(SRC)) {
    if (path === "lib/displayLabels.ts") continue;
    text.split("\n").forEach((line, i) => {
      const bad: string[] = [];
      for (const m of line.matchAll(RAW_FALLBACK)) {
        const index = m[1]!.trim();
        if (m[2]!.replace(/\?$/, "") === index) bad.push(m[0]);
      }
      if (UNDERSCORES.test(line)) bad.push(".replace(/_/g, \" \")");
      for (const b of bad) {
        if (!ALLOW.some(([p, pattern]) => p === path && line.includes(pattern))) out.push(`${path}:${i + 1}  ${b}`);
      }
    });
  }
  return out;
}

describe("code fallbacks (decision 14)", () => {
  it("keeps every code fallback in displayLabels.ts", () => {
    const bad = findings();
    expect(bad, `use labelFor(map, code) from lib/displayLabels:\n${bad.join("\n")}`).toEqual([]);
  });

  it("keeps no stale exception", () => {
    const all = sources(SRC);
    for (const [path, pattern, reason] of ALLOW) {
      expect(all.find((s) => s.path === path)?.text.includes(pattern), `${path}: ${pattern}`).toBe(true);
      expect(reason.length).toBeGreaterThan(5);
    }
  });
});
