import { describe, expect, it } from "vitest";

import {
  actionGroups,
  AUDIT_PARAMS,
  auditParams,
  checkFilters,
  choiceOf,
  diffRows,
  fieldOfError,
  isTextDigest,
  periodChoice,
  sameValue,
  VALUE_KEY,
} from "./audit";
import { istDay } from "./format";

describe("auditParams", () => {
  it("passes the ten names unchanged, omits empty values and drops unknown names", () => {
    const all = Object.fromEntries(AUDIT_PARAMS.map((n) => [n, `v-${n}`]));
    expect(auditParams(all)).toEqual(all);
    expect(AUDIT_PARAMS).toHaveLength(10);
    expect(auditParams({ user: "", actor: "  ", case: " GHC-1 ", offset: "50", cursor: "x", limit: "200" })).toEqual({
      case: "GHC-1",
    });
    expect(auditParams({})).toEqual({});
  });
});

describe("periodChoice", () => {
  it("Today, Last 7 days and Last 30 days include today", () => {
    expect(periodChoice("today", "2026-10-14")).toEqual({ from: "2026-10-14", to: "2026-10-14" });
    expect(periodChoice("last_7", "2026-10-14")).toEqual({ from: "2026-10-08", to: "2026-10-14" });
    expect(periodChoice("last_30", "2026-10-14")).toEqual({ from: "2026-09-15", to: "2026-10-14" });
  });

  it("Any time and Choose dates send neither date", () => {
    expect(periodChoice("any", "2026-10-14")).toBeNull();
    expect(periodChoice("custom", "2026-10-14")).toBeNull();
  });

  it("uses the IST day near midnight UTC", () => {
    const today = istDay(new Date("2026-10-13T18:45:00Z")); // 00:15 IST on 14 Oct
    expect(today).toBe("2026-10-14");
    expect(periodChoice("today", today)).toEqual({ from: "2026-10-14", to: "2026-10-14" });
    expect(istDay(new Date("2026-10-13T18:15:00Z"))).toBe("2026-10-13");
  });

  it("reads the quick choice back from the URL's dates", () => {
    expect(choiceOf(undefined, undefined, "2026-10-14")).toBe("any");
    expect(choiceOf("2026-10-14", "2026-10-14", "2026-10-14")).toBe("today");
    expect(choiceOf("2026-10-08", "2026-10-14", "2026-10-14")).toBe("last_7");
    expect(choiceOf("2026-10-01", "2026-10-05", "2026-10-14")).toBe("custom");
    expect(choiceOf("2026-10-01", undefined, "2026-10-14")).toBe("custom");
  });
});

describe("checkFilters", () => {
  const today = "2026-10-14";
  it("Name contains takes 2 to 100 characters", () => {
    expect(checkFilters({ actor: "a" }, today)).toEqual({ actor: "length" });
    expect(checkFilters({ actor: "a".repeat(101) }, today)).toEqual({ actor: "length" });
    expect(checkFilters({ actor: "ab" }, today)).toBeNull();
    expect(checkFilters({ actor: "a".repeat(100) }, today)).toBeNull();
    expect(checkFilters({ actor: "" }, today)).toBeNull();
  });

  it("refuses an end before the start and a start after today", () => {
    expect(checkFilters({ from: "2026-10-10", to: "2026-10-09" }, today)).toEqual({ period: "order" });
    expect(checkFilters({ from: "2026-10-15" }, today)).toEqual({ period: "future" });
    expect(checkFilters({ from: "2026-10-01", to: "2026-10-14" }, today)).toBeNull();
    expect(checkFilters({ to: "2026-10-01" }, today)).toBeNull();
  });

  it("refuses a record id that is not a UUID", () => {
    expect(checkFilters({ entity_id: "abc" }, today)).toEqual({ entity_id: "uuid" });
    expect(checkFilters({ entity_id: "0192a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b" }, today)).toBeNull();
  });

  it("reports every problem at once", () => {
    expect(checkFilters({ actor: "x", from: "2026-10-12", to: "2026-10-11", entity_id: "1" }, today)).toEqual({
      actor: "length",
      period: "order",
      entity_id: "uuid",
    });
  });
});

describe("actionGroups", () => {
  const labels = { custody: "Custody", auth: "Sign-in and password" };
  it("groups codes by prefix, sorted by label, codes sorted, each with its prefix", () => {
    const groups = actionGroups(["custody.sent", "auth.login", "custody.recalled", "custody.sent"], labels);
    expect(groups).toEqual([
      { prefix: "custody.", label: "Custody", codes: ["custody.recalled", "custody.sent"] },
      { prefix: "auth.", label: "Sign-in and password", codes: ["auth.login"] },
    ]);
  });

  it("labels an unknown prefix by itself", () => {
    expect(actionGroups(["brand_new.thing"], labels)).toEqual([
      { prefix: "brand_new.", label: "brand_new", codes: ["brand_new.thing"] },
    ]);
  });

  it("puts a code without a dot in its own group, without an All entry", () => {
    const groups = actionGroups(["login", "custody.sent"], labels);
    expect(groups).toContainEqual({ prefix: null, label: "login", codes: ["login"] });
    expect(groups).toHaveLength(2);
  });
});

describe("diffRows", () => {
  it("takes the union of keys in order of appearance and marks differences", () => {
    const rows = diffRows({ name: "Old", code: "EDU", kind: "department" }, { name: "New", code: "EDU", notes: "x" });
    expect(rows.map((r) => r.key)).toEqual(["name", "code", "kind", "notes"]);
    expect(rows.map((r) => r.changed)).toEqual([true, false, true, true]);
    expect(rows[2]).toEqual({ key: "kind", before: "department", after: undefined, changed: true });
  });

  it("compares nested objects and lists by value", () => {
    const rows = diffRows(
      { meta: { a: 1, b: [1, 2] }, list: [1, { x: 1 }] },
      { meta: { b: [1, 2], a: 1 }, list: [1, { x: 2 }] },
    );
    expect(rows.map((r) => [r.key, r.changed])).toEqual([
      ["meta", false],
      ["list", true],
    ]);
  });

  it("handles one side null or absent", () => {
    expect(diffRows(null, { status: "active" })).toEqual([
      { key: "status", before: undefined, after: "active", changed: true },
    ]);
    expect(diffRows({ status: "active" }, undefined)).toEqual([
      { key: "status", before: "active", after: undefined, changed: true },
    ]);
    expect(diffRows({ a: null }, { a: undefined })[0]!.changed).toBe(false);
    expect(diffRows(null, null)).toEqual([]);
    expect(diffRows({}, {})).toEqual([]);
  });

  it("shows a value that is not an object under one row", () => {
    expect(diffRows("x", "y")).toEqual([{ key: VALUE_KEY, before: "x", after: "y", changed: true }]);
    expect(sameValue([1], { 0: 1 })).toBe(false);
  });
});

describe("isTextDigest", () => {
  it("is exactly {length, sha256}", () => {
    expect(isTextDigest({ length: 12, sha256: "ab".repeat(32) })).toBe(true);
    expect(isTextDigest({ length: 12, sha256: "ab", extra: 1 })).toBe(false);
    expect(isTextDigest({ length: 12 })).toBe(false);
    expect(isTextDigest(null)).toBe(false);
    expect(isTextDigest(["length", "sha256"])).toBe(false);
  });
});

describe("fieldOfError", () => {
  it("unknown_user goes to the field that was sent, or both", () => {
    expect(fieldOfError("unknown_user", { user: "a@b" })).toEqual(["user"]);
    expect(fieldOfError("unknown_user", { about_user: "a@b" })).toEqual(["about_user"]);
    expect(fieldOfError("unknown_user", { user: "a@b", about_user: "c@d" })).toEqual(["user", "about_user"]);
  });

  it("not_found to Case, bad_office to Office, bad_period to Period, bad_actor to Name contains", () => {
    expect(fieldOfError("not_found", { case: "GHC-X" })).toEqual(["case"]);
    expect(fieldOfError("bad_office", { office: "NOPE" })).toEqual(["office"]);
    expect(fieldOfError("bad_period", { from: "2026-10-02", to: "2026-10-01" })).toEqual(["period"]);
    expect(fieldOfError("bad_actor", { actor: "x" })).toEqual(["actor"]);
  });

  it("anything else goes to the banner", () => {
    expect(fieldOfError("search_timeout", {})).toEqual([]);
    expect(fieldOfError("bad_cursor", {})).toEqual([]);
  });
});
