import { describe, expect, it } from "vitest";

import { signalText } from "./signals";

describe("signal chips", () => {
  it.each([
    [{ kind: "counsel_code", matched: "SC, EDU", weight: 0.9 }, "Code: SC, EDU"],
    [{ kind: "keyword", matched: "university" }, "Keyword: university"],
    [{ kind: "name_pattern", matched: "GAUHATI UNIVERSITY" }, "Name: GAUHATI UNIVERSITY"],
    [{ kind: "linked_case", matched: "WP(C)/2417/2026" }, "Linked: WP(C)/2417/2026"],
    [{ kind: "watchlist", matched: "ASHC010012342026" }, "Watchlist"],
    [{ kind: "suggested_unit", office_code: "EDU-DSE" }, "Suggested unit: EDU-DSE"],
  ])("%o → %s", (signal, chip) => {
    expect(signalText(signal)).toBe(chip);
  });

  it("an unknown kind shows its name and match, never raw JSON", () => {
    expect(signalText({ kind: "new_kind", matched: "x", ref: { a: 1 } })).toBe("new kind: x");
    expect(signalText({})).toBe("Signal");
  });
});
