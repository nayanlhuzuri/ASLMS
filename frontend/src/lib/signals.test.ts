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

  it("a partial code shows the server's reason, or its fields without one", () => {
    const reason = "Code SC, EDU found inside SC, EDU, DSE on the cause list of 23 Oct 2026";
    expect(signalText({ kind: "counsel_code_partial", matched: "SC, EDU", printed: "SC, EDU, DSE", relation: "contained", reason, weight: 0.6 })).toBe(reason);
    expect(signalText({ kind: "counsel_code_partial", matched: "SC, EDU", printed: "SC, EDU, DSE" })).toBe("Partial code: SC, EDU in SC, EDU, DSE");
    expect(signalText({ kind: "counsel_code_partial", matched: "SC, EDU" })).toBe("Partial code: SC, EDU");
    expect(signalText({ kind: "counsel_code_partial" })).toBe("Partial code");
  });

  it("an unknown kind shows its name and match, never raw JSON", () => {
    expect(signalText({ kind: "new_kind", matched: "x", ref: { a: 1 } })).toBe("new kind: x");
    expect(signalText({})).toBe("Signal");
  });
});
