/**
 * The kit's OfficeName (design portal-names-and-labels, decision 5): a payload name wins, else the name from
 * `GET /reference/offices` with the code as the title (" · Inactive" for an inactive office); a code the map does not
 * hold, or any code after a refusal, shows as plain muted text; null shows "—"; with `href` a link; never `mono`.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OfficeNames } from "@/lib/api/types";
import { nameOptions, officeName } from "@/lib/officeNames";
import { browserApi, json, renderWithClient } from "@/test/render";

import { OfficeName } from "./OfficeName";

const NAMES: OfficeNames = {
  items: [
    { code: "GOA", name: "Government of Assam", kind: "state", tier: "state", department_code: null, is_active: true },
    { code: "EDU", name: "Education", kind: "department", tier: "department", department_code: "EDU", is_active: true },
    { code: "EDU-OLD", name: "Old Education Cell", kind: "unit", tier: "directorate", department_code: "EDU", is_active: false },
  ],
};

function withNames() {
  return browserApi({ "GET /reference/offices": NAMES });
}

describe("OfficeName", () => {
  it("prefers a payload name", async () => {
    withNames();
    renderWithClient(<OfficeName code="EDU" name="Education Department" />);
    expect(await screen.findByText("Education Department")).toHaveAttribute("title", "EDU");
  });

  it("shows the map's name with the code as the title, never in mono", async () => {
    withNames();
    renderWithClient(<OfficeName code="EDU" />);
    const name = await screen.findByText("Education");
    expect(name).toHaveAttribute("title", "EDU");
    expect(name.className).not.toMatch(/mono/);
    expect(name.closest(".mono")).toBeNull();
  });

  it("adds · Inactive to the title of an inactive office", async () => {
    withNames();
    renderWithClient(<OfficeName code="EDU-OLD" />);
    expect(await screen.findByText("Old Education Cell")).toHaveAttribute("title", "EDU-OLD · Inactive");
  });

  it("shows a code the map does not hold as muted plain text, and never invents a name", async () => {
    const api = withNames();
    renderWithClient(<OfficeName code="NEW-UNIT" />);
    await screen.findByText("NEW-UNIT");
    expect(api.calls.some((c) => c.path === "/reference/offices")).toBe(true);
    expect(screen.getByText("NEW-UNIT")).toHaveClass("muted");
  });

  it("shows codes after a refusal (403)", async () => {
    browserApi({ "GET /reference/offices": () => json(403, { detail: "cases.view_scope is not enabled for you" }) });
    renderWithClient(<OfficeName code="EDU" />);
    expect(await screen.findByText("EDU")).toHaveClass("muted");
  });

  it("shows — for no code", () => {
    withNames();
    renderWithClient(<OfficeName code={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("is a link with href", async () => {
    withNames();
    renderWithClient(<OfficeName code="EDU" href="/audit?office=EDU" />);
    expect(await screen.findByRole("link", { name: "Education" })).toHaveAttribute("href", "/audit?office=EDU");
  });
});

describe("officeName and nameOptions", () => {
  const map = new Map(NAMES.items.map((o) => [o.code, o]));

  it("names a code from the map, a payload name first, else the code; — for none", () => {
    expect(officeName("EDU", map)).toBe("Education");
    expect(officeName("EDU", map, "Education Department")).toBe("Education Department");
    expect(officeName("XYZ", map)).toBe("XYZ");
    expect(officeName(null, map)).toBe("—");
    expect(officeName("EDU", undefined)).toBe("EDU");
  });

  it("lists department options by name, sorted, with the code only when two share a name", () => {
    const options = nameOptions(
      [
        { code: "REV", name: "Revenue" },
        { code: "EDU", name: "Education" },
        { code: "SEC-EDU", name: "Education" },
        { code: "HEALTH", name: "Health" },
      ],
      ["HEALTH"],
    );
    expect(options).toEqual([
      { value: "EDU", label: "Education (EDU)" },
      { value: "SEC-EDU", label: "Education (SEC-EDU)" },
      { value: "REV", label: "Revenue" },
    ]);
  });
});
